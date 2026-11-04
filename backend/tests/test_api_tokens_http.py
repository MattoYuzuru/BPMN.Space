"""Токены доступа по HTTP на PostgreSQL (RFC-0007, шаг 1).

Вход по `Authorization: Bearer bps_…`, права маршрутов, ограничение проектами, отзыв и срок,
CSRF, запрет управления аккаунтом через токен, миграция. Нужен TEST_DATABASE_URL
(см. `make test-postgres`), иначе тесты пропускаются.
"""

# Фикстура `stack` импортируется из test_auth_http: параметры тестов её «переопределяют».
# ruff: noqa: F811

import os
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import inspect, select, text, update
from sqlalchemy.ext.asyncio import create_async_engine
from sse_starlette import ServerSentEvent
from starlette.requests import Request

from app.api.v1 import runs as runs_api
from app.api.v1.runs import run_events
from app.domain.api_tokens import hash_secret
from app.infra.db_models import ApiTokenRow
from app.services.auth import stream_user
from tests.test_auth_http import (  # noqa: F401 — фикстура `stack` подключается импортом
    API,
    DEMO,
    MIGRATIONS_DIR,
    NOBODY,
    Account,
    Stack,
    _finished_project,
    stack,
)

pytestmark = pytest.mark.asyncio

ALL_SCOPES = [
    "projects:read",
    "projects:write",
    "sources:write",
    "sources:delete",
    "runs:start",
    "questions:answer",
]


class Agent:
    """Клиент агента: только заголовок `Authorization`, без cookie и CSRF."""

    def __init__(self, stack: Stack, secret: str) -> None:
        self.http = AsyncClient(transport=ASGITransport(app=stack.app), base_url="http://t")
        self.secret = secret

    async def request(self, method: str, path: str, **kwargs: Any) -> Response:
        headers = {"authorization": f"Bearer {self.secret}", **kwargs.pop("headers", {})}
        return await self.http.request(method, f"{API}{path}", headers=headers, **kwargs)

    async def get(self, path: str, **kwargs: Any) -> Response:
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> Response:
        return await self.request("POST", path, **kwargs)


async def _issue(owner: Account, **body: Any) -> dict[str, Any]:
    created = await owner.post("/me/api-tokens", json={"name": "Claude Code", **body})
    assert created.status_code == 201, created.text
    return created.json()


async def test_token_lifecycle_stores_only_hash(stack: Stack) -> None:
    owner = await stack.user("token-owner@example.com")
    issued = await _issue(owner)
    secret = issued["secret"]

    assert secret.startswith("bps_")
    assert issued["token_prefix"] == secret[:10]
    assert issued["scopes"] == ["projects:read", "questions:answer"]
    assert issued["project_ids"] is None
    created_at = datetime.fromisoformat(issued["created_at"])
    assert datetime.fromisoformat(issued["expires_at"]) - created_at == timedelta(days=30)

    listed = (await owner.get("/me/api-tokens")).json()["items"]
    assert [item["id"] for item in listed] == [issued["id"]]
    assert "secret" not in listed[0]
    assert secret not in str(listed)

    async with stack.database.sessions() as session:
        row = await session.get(ApiTokenRow, UUID(issued["id"]))
        assert row is not None
        assert row.token_hash == hash_secret(secret)
        assert secret not in str(
            [getattr(row, column.key) for column in inspect(ApiTokenRow).columns]
        )

    agent = Agent(stack, secret)
    me = await agent.get("/auth/me")
    assert me.status_code == 200, me.text
    assert me.json()["id"] == owner.user_id
    session_state = (await agent.get("/auth/session")).json()
    assert session_state["user"]["id"] == owner.user_id
    assert (await agent.get("/projects")).status_code == 200
    used = (await owner.get("/me/api-tokens")).json()["items"][0]
    assert used["last_used_at"] is not None

    revoked = await owner.delete(f"/me/api-tokens/{issued['id']}")
    assert revoked.status_code == 204
    assert (await owner.delete(f"/me/api-tokens/{issued['id']}")).status_code == 404
    assert (await owner.get("/me/api-tokens")).json()["items"] == []
    denied = await agent.get("/projects")
    assert denied.status_code == 401
    unknown = await Agent(stack, "bps_" + "x" * 43).get("/projects")
    assert unknown.status_code == 401
    assert denied.json() == unknown.json()


async def test_expired_and_malformed_tokens_get_the_same_401(stack: Stack) -> None:
    owner = await stack.user("token-expired@example.com")
    issued = await _issue(owner, expires_in_days=7)
    agent = Agent(stack, issued["secret"])
    assert (await agent.get("/projects")).status_code == 200

    async with stack.database.sessions.begin() as session:
        await session.execute(
            update(ApiTokenRow)
            .where(ApiTokenRow.id == UUID(issued["id"]))
            .values(
                created_at=datetime.now(UTC) - timedelta(days=8),
                expires_at=datetime.now(UTC) - timedelta(seconds=1),
            )
        )
    expired = await agent.get("/projects")
    listed = (await owner.get("/me/api-tokens")).json()["items"]
    assert listed[0]["expired"] is True

    malformed = await Agent(stack, "not-a-token").get("/projects")
    empty = await Agent(stack, "").get("/projects")
    for response in (expired, malformed, empty):
        assert response.status_code == 401
        assert response.json() == expired.json()
    # 401 не раскрывает права маршрута: закрытый маршрут с плохим токеном — тоже 401.
    assert (await Agent(stack, "not-a-token").get("/me/api-tokens")).status_code == 401


async def test_scopes_limit_routes_with_russian_403(stack: Stack) -> None:
    owner = await stack.user("token-scopes@example.com")
    finished = await _finished_project(owner)
    project = finished["project"]
    reader = Agent(stack, (await _issue(owner))["secret"])

    assert (await reader.get(f"/projects/{project}")).status_code == 200
    assert (await reader.get(f"/projects/{project}/questions")).status_code == 200
    assert (await reader.get(f"/versions/{finished['version']}/xml")).status_code == 200
    assert (await reader.get(f"/runs/{finished['run']}")).status_code == 200
    answered = await reader.post(
        f"/questions/{finished['question']}/answer", json={"text": "Ответ агента"}
    )
    assert answered.status_code == 200, answered.text

    source = await reader.post(
        f"/projects/{project}/sources/text", json={"content": "Текст процесса от агента"}
    )
    assert source.status_code == 403
    assert "sources:write" in source.json()["detail"]
    assert "Доступ для агентов" in source.json()["detail"]
    run = await reader.post(f"/projects/{project}/runs", json={"mode": "analyze"})
    assert run.status_code == 403
    assert "runs:start" in run.json()["detail"]
    removed = await reader.request("DELETE", f"/sources/{finished['source']}")
    assert removed.status_code == 403
    assert "sources:delete" in removed.json()["detail"]
    renamed = await reader.request("PATCH", f"/projects/{project}", json={"title": "Новое"})
    assert renamed.status_code == 403
    assert "projects:write" in renamed.json()["detail"]

    writer = Agent(stack, (await _issue(owner, scopes=["sources:write"]))["secret"])
    added = await writer.post(
        f"/projects/{project}/sources/text", json={"content": "Текст процесса от агента"}
    )
    assert added.status_code == 201, added.text
    assert (await writer.get(f"/projects/{project}")).status_code == 403


async def test_token_never_exceeds_project_role(stack: Stack) -> None:
    owner = await stack.user("token-role@example.com")
    full = Agent(stack, (await _issue(owner, scopes=ALL_SCOPES))["secret"])
    # Демо-проект доступен только для чтения: право токена не повышает роль viewer.
    assert (await full.get(f"/projects/{DEMO}")).status_code == 200
    patched = await full.request("PATCH", f"/projects/{DEMO}", json={"title": "Взлом"})
    assert patched.status_code == 403
    assert "редактора" in patched.json()["detail"]
    other = await stack.user("token-role-other@example.com")
    foreign = await other.post("/projects", json={"title": "Чужой"})
    assert (await full.get(f"/projects/{foreign.json()['id']}")).status_code == 404


async def test_project_restriction_hides_other_projects(stack: Stack) -> None:
    owner = await stack.user("token-projects@example.com")
    allowed = (await owner.post("/projects", json={"title": "Договоры"})).json()["id"]
    hidden = (await owner.post("/projects", json={"title": "Закупки"})).json()["id"]
    other = await stack.user("token-projects-other@example.com")
    foreign = (await other.post("/projects", json={"title": "Чужой"})).json()["id"]

    rejected = await owner.post(
        "/me/api-tokens", json={"name": "x", "project_ids": [allowed, foreign]}
    )
    assert rejected.status_code == 404
    assert (
        await owner.post("/me/api-tokens", json={"name": "x", "project_ids": []})
    ).status_code == 422

    issued = await _issue(owner, scopes=ALL_SCOPES, project_ids=[allowed])
    assert issued["project_ids"] == [allowed]
    agent = Agent(stack, issued["secret"])

    page = (await agent.get("/projects")).json()
    assert [item["id"] for item in page["items"]] == [allowed]
    assert page["total"] == 1
    assert (await agent.get(f"/projects/{allowed}")).status_code == 200
    assert (await agent.get(f"/projects/{hidden}")).status_code == 404
    assert (await agent.get(f"/projects/{hidden}/versions")).status_code == 404
    assert (await agent.get(f"/projects/{DEMO}")).status_code == 404
    text_source = await agent.post(
        f"/projects/{hidden}/sources/text", json={"content": "Текст процесса"}
    )
    assert text_source.status_code == 404
    created = await agent.post("/projects", json={"title": "Новый"})
    assert created.status_code == 403
    assert "выбранными проектами" in created.json()["detail"]

    unrestricted = Agent(stack, (await _issue(owner, scopes=ALL_SCOPES))["secret"])
    made = await unrestricted.post("/projects", json={"title": "Новый от агента"})
    assert made.status_code == 201, made.text
    assert made.json()["access"] == "owner"


async def test_token_cannot_manage_account_secrets_or_sharing(stack: Stack) -> None:
    owner = await stack.user("token-closed@example.com")
    project = (await owner.post("/projects", json={"title": "Проект"})).json()["id"]
    agent = Agent(stack, (await _issue(owner, scopes=ALL_SCOPES))["secret"])
    closed = [
        ("GET", "/me/api-tokens", {}),
        ("POST", "/me/api-tokens", {"json": {"name": "ещё один", "scopes": ALL_SCOPES}}),
        ("DELETE", f"/me/api-tokens/{NOBODY}", {}),
        ("GET", "/me/llm-credentials", {}),
        ("POST", "/me/llm-credentials", {"json": {"provider": "openai", "api_key": "sk-test"}}),
        ("GET", f"/projects/{project}/share-links", {}),
        ("POST", f"/projects/{project}/share-links", {"json": {"role": "editor"}}),
        ("GET", f"/projects/{project}/members", {}),
        ("DELETE", f"/projects/{project}", {}),
        ("DELETE", f"/projects/{project}/membership", {}),
        ("POST", f"/projects/{project}/collaboration-ticket", {}),
        ("GET", "/me/onboarding", {}),
        ("POST", "/shares/unknown/accept", {}),
    ]
    for method, path, kwargs in closed:
        response = await agent.request(method, path, **kwargs)
        assert response.status_code == 403, (method, path, response.text)
        assert "недоступно по токену" in response.json()["detail"]
    # Выход работает только с cookie: без неё по токену сессию не закрыть.
    assert (await agent.post("/auth/session/logout")).status_code == 401
    assert (await owner.get(f"/projects/{project}")).status_code == 200
    assert len((await owner.get("/me/api-tokens")).json()["items"]) == 1


async def test_csrf_is_skipped_for_bearer_and_kept_for_cookie(stack: Stack) -> None:
    owner = await stack.user("token-csrf@example.com")
    agent = Agent(stack, (await _issue(owner, scopes=ALL_SCOPES))["secret"])
    created = await agent.post("/projects", json={"title": "Без CSRF"})
    assert created.status_code == 201, created.text

    no_csrf = await owner.http.post(f"{API}/projects", json={"title": "x"})
    assert no_csrf.status_code == 403
    assert no_csrf.json() == {"detail": "CSRF-токен отсутствует или не совпадает"}
    token_without_csrf = await owner.http.post(f"{API}/me/api-tokens", json={"name": "x"})
    assert token_without_csrf.status_code == 403

    # Неверный токен рядом с действующей cookie не откатывается на cookie.
    mixed = await owner.post(
        "/projects", json={"title": "x"}, headers={"authorization": "Bearer bps_" + "y" * 43}
    )
    assert mixed.status_code == 401


async def test_last_used_is_not_rewritten_within_a_minute(stack: Stack) -> None:
    owner = await stack.user("token-touch@example.com")
    issued = await _issue(owner)
    agent = Agent(stack, issued["secret"])
    assert (await agent.get("/projects")).status_code == 200

    async def last_used() -> datetime | None:
        async with stack.database.sessions() as session:
            return await session.scalar(
                select(ApiTokenRow.last_used_at).where(ApiTokenRow.id == UUID(issued["id"]))
            )

    first = await last_used()
    assert first is not None
    assert (await agent.get("/projects")).status_code == 200
    assert await last_used() == first


def _bearer_stream_request(stack: Stack, secret: str) -> Request:
    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    route = next(
        route for route in runs_api.router.routes if getattr(route, "path", "").endswith("/events")
    )
    return Request(
        {
            "type": "http",
            "app": stack.app,
            "headers": [(b"authorization", f"Bearer {secret}".encode())],
            "route": route,
        },
        receive=receive,
    )


async def test_run_stream_with_token_stops_after_revocation(stack: Stack) -> None:
    owner = await stack.user("token-stream@example.com")
    finished = await _finished_project(owner)
    issued = await _issue(owner)
    request = _bearer_stream_request(stack, issued["secret"])
    user = await stream_user(request)
    assert user is not None
    assert str(user.id) == owner.user_id

    response = await run_events(UUID(finished["run"]), request, stack.app.state.container, user)
    stream = cast(AsyncGenerator[ServerSentEvent], response.body_iterator)
    await anext(stream)
    assert (await owner.delete(f"/me/api-tokens/{issued['id']}")).status_code == 204
    try:
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
    finally:
        await stream.aclose()


async def test_token_input_validation(stack: Stack) -> None:
    owner = await stack.user("token-validation@example.com")
    cases = [
        {"name": ""},
        {"name": "x", "scopes": []},
        {"name": "x", "scopes": ["projects:admin"]},
        {"name": "x", "expires_in_days": 366},
        {"name": "x", "expires_in_days": 0},
    ]
    for body in cases:
        response = await owner.post("/me/api-tokens", json=body)
        assert response.status_code == 422, (body, response.text)
    year = await _issue(owner, expires_in_days=365)
    created_at = datetime.fromisoformat(year["created_at"])
    assert datetime.fromisoformat(year["expires_at"]) - created_at == timedelta(days=365)
    guest = await stack.guest()
    assert (await guest.get("/me/api-tokens")).status_code == 401


async def test_migration_0017_creates_and_drops_api_tokens() -> None:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL не задан; PostgreSQL-интеграционный тест пропущен")
    schema = f"test_{uuid4().hex}"
    admin = create_async_engine(url)
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))

    def migrate(sync_connection: Any, action: str, revision: str) -> None:
        config.attributes["connection"] = sync_connection
        getattr(command, action)(config, revision)

    def tables(sync_connection: Any) -> set[str]:
        return set(inspect(sync_connection).get_table_names())

    try:
        async with engine.begin() as connection:
            await connection.run_sync(migrate, "upgrade", "0017_api_tokens")
            assert "api_tokens" in await connection.run_sync(tables)
            user_id = uuid4()
            await connection.execute(
                text(
                    "INSERT INTO users (id, email, hashed_password, is_active, is_superuser, "
                    "is_verified) VALUES (:id, 'm@example.com', 'x', true, false, false)"
                ),
                {"id": user_id},
            )
            insert = text(
                "INSERT INTO api_tokens (id, user_id, name, token_prefix, token_hash, scopes, "
                "expires_at, created_at) VALUES (:id, :user, 'n', 'bps_aaaaaa', :hash, "
                ":scopes, now() + interval '1 day', now())"
            )
            await connection.execute(
                insert,
                {"id": uuid4(), "user": user_id, "hash": "a" * 64, "scopes": ["projects:read"]},
            )
            with pytest.raises(Exception, match="ck_api_tokens_scopes_known"):
                async with connection.begin_nested():
                    await connection.execute(
                        insert,
                        {"id": uuid4(), "user": user_id, "hash": "b" * 64, "scopes": ["admin"]},
                    )
            await connection.run_sync(migrate, "downgrade", "0016_source_derivation")
            assert "api_tokens" not in await connection.run_sync(tables)
            await connection.run_sync(migrate, "upgrade", "head")
            assert "api_tokens" in await connection.run_sync(tables)
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()
