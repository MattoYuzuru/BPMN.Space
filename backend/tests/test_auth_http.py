"""HTTP-тесты с включённой авторизацией на PostgreSQL (временная схема).

Проверяют то, чего не видят тесты без auth: гость везде получает 401, чужой проект скрыт (404),
демо-проект только для чтения, роли owner/editor/viewer, ссылки доступа, заголовки XML.
Нужен TEST_DATABASE_URL (см. `make test-postgres`), иначе тесты пропускаются.
"""

import asyncio
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import Settings
from app.container import build_container
from app.domain.models import Project
from app.infra.database import Database
from app.infra.db_models import ProjectShareLinkRow
from app.infra.seed import DEMO_PROJECT_ID, SeedData, build_seed
from app.main import create_app

API = "/api/v1"
PASSWORD = "test-password-long-enough"  # noqa: S105
DEMO = str(DEMO_PROJECT_ID)
MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"
NOBODY = "00000000-0000-4000-8000-000000000000"

pytestmark = pytest.mark.asyncio


def _demo_seed() -> SeedData:
    """Сид из одного демо-проекта: быстрее полного набора, но с вопросами и версиями."""
    full = build_seed()
    keep = {DEMO_PROJECT_ID}
    return SeedData(
        projects=[p for p in full.projects if p.id in keep],
        sources=[s for s in full.sources if s.project_id in keep],
        questions=[q for q in full.questions if q.project_id in keep],
        runs=[r for r in full.runs if r.project_id in keep],
        versions=[v for v in full.versions if v.project_id in keep],
    )


@dataclass
class Account:
    """Клиент одного пользователя со своей cookie-сессией и CSRF-токеном."""

    http: AsyncClient
    csrf: str = ""
    email: str = ""
    user_id: str = ""

    async def request(self, method: str, path: str, **kwargs: Any) -> Response:
        headers = {"x-csrf-token": self.csrf, **kwargs.pop("headers", {})}
        return await self.http.request(method, f"{API}{path}", headers=headers, **kwargs)

    async def get(self, path: str, **kwargs: Any) -> Response:
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> Response:
        return await self.request("POST", path, **kwargs)

    async def patch(self, path: str, **kwargs: Any) -> Response:
        return await self.request("PATCH", path, **kwargs)

    async def put(self, path: str, **kwargs: Any) -> Response:
        return await self.request("PUT", path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> Response:
        return await self.request("DELETE", path, **kwargs)


@dataclass
class Stack:
    app: Any
    database: Database
    settings: Settings

    async def guest(self) -> Account:
        account = Account(AsyncClient(transport=ASGITransport(app=self.app), base_url="http://t"))
        account.csrf = (await account.http.get(f"{API}/auth/csrf")).json()["csrf_token"]
        return account

    async def user(self, email: str) -> Account:
        account = await self.guest()
        registered = await account.post(
            "/auth/register", json={"email": email, "password": PASSWORD}
        )
        assert registered.status_code == 201, registered.text
        login = await account.post(
            "/auth/session/login", data={"username": email, "password": PASSWORD}
        )
        assert login.status_code == 204, login.text
        account.email = email
        account.user_id = registered.json()["id"]
        return account


@pytest.fixture
async def stack(tmp_path: Path) -> AsyncIterator[Stack]:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL не задан; PostgreSQL-интеграционный тест пропущен")
    schema = f"test_{uuid4().hex}"
    admin = create_async_engine(url)
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    database = Database(url, connect_args={"server_settings": {"search_path": schema}})
    settings = Settings(
        auth_enabled=True,
        database_url=None,
        app_env="test",
        mock_delay_scale=0,
        seed_demo_data=False,
        rate_limit_enabled=False,
        upload_dir=str(tmp_path),
    )
    container = build_container(settings, database=database)
    await database.initialize()
    await database.seed(_demo_seed)
    app = create_app(settings, container=container)
    try:
        yield Stack(app, database, settings)
    finally:
        await database.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


async def _finished_project(owner: Account) -> dict[str, Any]:
    """Проект владельца с источником, завершённым прогоном, вопросом и версией схемы."""
    created = await owner.post("/projects/from-example", json={"example_id": "tp861"})
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]
    run_id = ""
    run: dict[str, Any] = {}
    for mode in ("analyze", "build"):
        started = await owner.post(f"/projects/{project_id}/runs", json={"mode": mode})
        assert started.status_code == 202, started.text
        run_id = started.json()["id"]
        for _ in range(100):
            run = (await owner.get(f"/runs/{run_id}")).json()
            if run["status"] not in {"queued", "running"}:
                break
            await asyncio.sleep(0.05)
        assert run["status"] == "succeeded", run
    detail = (await owner.get(f"/projects/{project_id}")).json()
    assert detail["latest_version"]
    assert detail["questions"]
    assert detail["sources"]
    return {
        "project": project_id,
        "run": run_id,
        "source": detail["sources"][0]["id"],
        "question": detail["questions"][0]["id"],
        "version": detail["latest_version"]["id"],
        "xml": (await owner.get(f"/versions/{detail['latest_version']['id']}")).json()["xml"],
    }


# ---------- сессия и CSRF ----------


async def test_register_login_logout_and_session_state(stack: Stack) -> None:
    guest = await stack.guest()
    state = await guest.get("/auth/session")
    assert state.status_code == 200
    assert state.json() == {"auth_enabled": True, "user": None}
    assert (await guest.get("/auth/me")).status_code == 401

    no_csrf = await guest.http.post(
        f"{API}/auth/register", json={"email": "a@example.com", "password": PASSWORD}
    )
    assert no_csrf.status_code == 403
    assert no_csrf.json() == {"detail": "CSRF-токен отсутствует или не совпадает"}
    wrong_csrf = await guest.post(
        "/auth/register",
        json={"email": "a@example.com", "password": PASSWORD},
        headers={"x-csrf-token": "forged"},
    )
    assert wrong_csrf.status_code == 403

    short = await guest.post("/auth/register", json={"email": "a@example.com", "password": "short"})
    assert short.status_code == 422
    assert "password" in short.json()["detail"]

    account = await stack.user("analyst@example.com")
    duplicate = await guest.post(
        "/auth/register", json={"email": "analyst@example.com", "password": PASSWORD}
    )
    assert duplicate.status_code == 400
    assert duplicate.json() == {"detail": "REGISTER_USER_ALREADY_EXISTS"}

    state = (await account.get("/auth/session")).json()
    assert state["auth_enabled"] is True
    assert state["user"] == {"id": account.user_id, "email": "analyst@example.com"}

    bad = await guest.post(
        "/auth/session/login",
        data={"username": "analyst@example.com", "password": "wrong-password"},
    )
    assert bad.status_code == 400
    assert bad.json() == {"detail": "LOGIN_BAD_CREDENTIALS"}

    # Изменяющий запрос залогиненного без CSRF отклоняется.
    assert (await account.http.post(f"{API}/projects", json={"title": "x"})).status_code == 403
    assert (await account.post("/projects", json={"title": "x"})).status_code == 201

    assert (await account.post("/auth/session/logout")).status_code == 204
    assert (await account.get("/auth/session")).json()["user"] is None
    assert (await account.get("/projects")).status_code == 401


# ---------- гость ----------


def _guest_calls() -> list[tuple[str, str, dict[str, Any]]]:
    pid, oid = NOBODY, NOBODY
    return [
        ("GET", "/projects", {}),
        ("POST", "/projects", {"json": {"title": "x"}}),
        ("POST", "/projects/from-example", {"json": {"example_id": "tp861"}}),
        ("GET", f"/projects/{pid}", {}),
        ("PATCH", f"/projects/{pid}", {"json": {"title": "x"}}),
        ("DELETE", f"/projects/{pid}", {}),
        ("POST", f"/projects/{pid}/sources/text", {"json": {"content": "текст процесса"}}),
        ("POST", f"/projects/{pid}/sources/file", {"files": {"file": ("a.txt", b"text")}}),
        ("PATCH", f"/sources/{oid}", {"json": {"title": "x"}}),
        ("DELETE", f"/sources/{oid}", {}),
        ("GET", f"/projects/{pid}/questions", {}),
        ("POST", f"/questions/{oid}/answer", {"json": {"text": "ответ"}}),
        ("POST", f"/questions/{oid}/ignore", {}),
        ("POST", f"/questions/{oid}/reopen", {}),
        ("POST", f"/projects/{pid}/runs", {"json": {"mode": "analyze"}}),
        ("GET", f"/runs/{oid}", {}),
        ("GET", f"/runs/{oid}/events", {}),
        ("GET", f"/projects/{pid}/versions", {}),
        ("GET", f"/versions/{oid}", {}),
        ("GET", f"/versions/{oid}/xml", {}),
        ("PUT", f"/projects/{pid}/diagram", {"json": {"xml": "<a/>"}}),
        ("POST", f"/projects/{pid}/assistant", {"json": {"message": "привет"}}),
        ("POST", "/assistant/chat", {"json": {"message": "привет", "project_title": "Процесс"}}),
        ("POST", "/transcriptions", {"files": {"file": ("a.webm", b"1234", "audio/webm")}}),
        ("GET", f"/projects/{pid}/members", {}),
        ("DELETE", f"/projects/{pid}/members/{oid}", {}),
        ("GET", f"/projects/{pid}/share-links", {}),
        ("POST", f"/projects/{pid}/share-links", {"json": {"role": "viewer"}}),
        ("DELETE", f"/projects/{pid}/share-links/{oid}", {}),
        ("GET", "/auth/me", {}),
    ]


async def test_guest_is_rejected_everywhere_but_public_routes(stack: Stack) -> None:
    guest = await stack.guest()
    for method, path, kwargs in _guest_calls():
        response = await guest.request(method, path, **kwargs)
        assert response.status_code == 401, (method, path, response.status_code, response.text)

    assert (await guest.get("/examples")).status_code == 200
    assert (await guest.http.get("/health")).status_code == 200
    assert (await guest.get("/shares/unknown-token")).status_code == 404
    assert (await guest.get(f"/shares/unknown-token/versions/{NOBODY}/xml")).status_code == 404
    # Приглашение без входа: известная ссылка отвечает 401, но не открывает данные.
    assert (await guest.post("/shares/unknown-token/accept")).status_code == 404


# ---------- IDOR ----------


async def test_other_user_cannot_see_or_change_private_project(stack: Stack) -> None:
    owner = await stack.user("owner@example.com")
    intruder = await stack.user("intruder@example.com")
    ids = await _finished_project(owner)
    pid = ids["project"]

    listed = (await intruder.get("/projects")).json()
    assert [item["id"] for item in listed["items"]] == [DEMO]
    assert listed["total"] == 1
    assert pid in [item["id"] for item in (await owner.get("/projects")).json()["items"]]

    hidden: list[tuple[str, str, dict[str, Any]]] = [
        ("GET", f"/projects/{pid}", {}),
        ("PATCH", f"/projects/{pid}", {"json": {"title": "взлом"}}),
        ("DELETE", f"/projects/{pid}", {}),
        ("POST", f"/projects/{pid}/sources/text", {"json": {"content": "чужой текст"}}),
        ("POST", f"/projects/{pid}/sources/file", {"files": {"file": ("a.txt", b"text")}}),
        ("PATCH", f"/sources/{ids['source']}", {"json": {"title": "x"}}),
        ("DELETE", f"/sources/{ids['source']}", {}),
        ("GET", f"/projects/{pid}/questions", {}),
        ("POST", f"/questions/{ids['question']}/answer", {"json": {"text": "ответ"}}),
        ("POST", f"/questions/{ids['question']}/ignore", {}),
        ("POST", f"/questions/{ids['question']}/reopen", {}),
        ("POST", f"/projects/{pid}/runs", {"json": {"mode": "analyze"}}),
        ("GET", f"/runs/{ids['run']}", {}),
        ("GET", f"/runs/{ids['run']}/events", {}),
        ("GET", f"/projects/{pid}/versions", {}),
        ("GET", f"/versions/{ids['version']}", {}),
        ("GET", f"/versions/{ids['version']}/xml", {}),
        ("PUT", f"/projects/{pid}/diagram", {"json": {"xml": ids["xml"]}}),
        ("POST", f"/projects/{pid}/assistant", {"json": {"message": "привет"}}),
        ("GET", f"/projects/{pid}/members", {}),
        ("GET", f"/projects/{pid}/share-links", {}),
        ("POST", f"/projects/{pid}/share-links", {"json": {"role": "viewer"}}),
    ]
    for method, path, kwargs in hidden:
        response = await intruder.request(method, path, **kwargs)
        # Права владельца на ссылки/участников проверяются после доступа к проекту: тоже 404.
        assert response.status_code == 404, (method, path, response.status_code, response.text)

    # Владелец ничего не потерял.
    detail = (await owner.get(f"/projects/{pid}")).json()
    assert detail["title"] != "взлом"
    assert len(detail["sources"]) == 1


# ---------- демо-проект ----------


async def test_demo_project_is_read_only_for_everyone(stack: Stack) -> None:
    user = await stack.user("reader@example.com")
    detail = await user.get(f"/projects/{DEMO}")
    assert detail.status_code == 200
    assert detail.json()["access"] == "viewer"
    page = (await user.get("/projects")).json()
    assert page["items"][0]["access"] == "viewer"

    questions = (await user.get(f"/projects/{DEMO}/questions")).json()
    version_id = detail.json()["latest_version"]["id"]
    source_id = detail.json()["sources"][0]["id"]
    run_id = (await user.post("/projects/from-example", json={"example_id": "tp861"})).status_code
    assert run_id == 201  # создать свой проект можно

    assert (await user.get(f"/versions/{version_id}/xml")).status_code == 200
    forbidden: list[tuple[str, str, dict[str, Any]]] = [
        ("PATCH", f"/projects/{DEMO}", {"json": {"title": "x"}}),
        ("DELETE", f"/projects/{DEMO}", {}),
        ("POST", f"/projects/{DEMO}/sources/text", {"json": {"content": "текст процесса"}}),
        ("PATCH", f"/sources/{source_id}", {"json": {"title": "x"}}),
        ("DELETE", f"/sources/{source_id}", {}),
        ("POST", f"/questions/{questions[0]['id']}/ignore", {}),
        ("POST", f"/projects/{DEMO}/runs", {"json": {"mode": "analyze"}}),
        ("PUT", f"/projects/{DEMO}/diagram", {"json": {"xml": "<a/>"}}),
    ]
    for method, path, kwargs in forbidden:
        response = await user.request(method, path, **kwargs)
        assert response.status_code == 403, (method, path, response.status_code, response.text)
    # Но не управление доступом: демо-проект не принадлежит никому.
    assert (
        await user.post(f"/projects/{DEMO}/share-links", json={"role": "viewer"})
    ).status_code == 403


async def test_projects_created_without_public_flag_stay_private(stack: Stack) -> None:
    """Открытым на чтение становится только сид; всё остальное по умолчанию закрыто."""
    stranger = await stack.user("stranger@example.com")
    now = datetime.now(UTC)
    legacy = Project(
        id=uuid4(), title="Старый проект", description=None, created_at=now, updated_at=now
    )
    await stack.database.store.repositories().projects.add(legacy)

    assert (await stranger.get(f"/projects/{legacy.id}")).status_code == 404
    ids = [item["id"] for item in (await stranger.get("/projects")).json()["items"]]
    assert str(legacy.id) not in ids
    assert DEMO in ids


# ---------- роли ----------


async def test_editor_can_edit_but_not_delete_or_share(stack: Stack) -> None:
    owner = await stack.user("boss@example.com")
    editor = await stack.user("colleague@example.com")
    pid = (await _finished_project(owner))["project"]

    created = await owner.post(f"/projects/{pid}/share-links", json={"role": "editor"})
    assert created.status_code == 201, created.text
    token = created.json()["url_path"].removeprefix("/share/")

    # До принятия приглашения доступа нет.
    assert (await editor.get(f"/projects/{pid}")).status_code == 404
    assert (await editor.post(f"/shares/{token}/accept")).status_code == 200
    detail = await editor.get(f"/projects/{pid}")
    assert detail.status_code == 200
    assert detail.json()["access"] == "editor"
    assert (await editor.get("/projects")).json()["items"][0]["access"] == "editor"

    renamed = await editor.patch(f"/projects/{pid}", json={"title": "Новое название"})
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Новое название"
    added = await editor.post(f"/projects/{pid}/sources/text", json={"content": "дополнение"})
    assert added.status_code == 201

    denied = [
        ("DELETE", f"/projects/{pid}", {}),
        ("GET", f"/projects/{pid}/members", {}),
        ("GET", f"/projects/{pid}/share-links", {}),
        ("POST", f"/projects/{pid}/share-links", {"json": {"role": "viewer"}}),
        ("DELETE", f"/projects/{pid}/share-links/{created.json()['id']}", {}),
        ("DELETE", f"/projects/{pid}/members/{owner.user_id}", {}),
    ]
    for method, path, kwargs in denied:
        response = await editor.request(method, path, **kwargs)
        assert response.status_code == 403, (method, path, response.status_code)

    members = (await owner.get(f"/projects/{pid}/members")).json()
    assert [m["email"] for m in members] == ["colleague@example.com"]
    assert (await owner.delete(f"/projects/{pid}/members/{editor.user_id}")).status_code == 204
    assert (await editor.get(f"/projects/{pid}")).status_code == 404

    assert (await owner.delete(f"/projects/{pid}")).status_code == 204
    assert (await owner.get(f"/projects/{pid}")).status_code == 404


async def test_viewer_link_is_read_only_and_does_not_open_the_project(stack: Stack) -> None:
    owner = await stack.user("author@example.com")
    other = await stack.user("someone@example.com")
    guest = await stack.guest()
    ids = await _finished_project(owner)
    pid = ids["project"]

    link = await owner.post(f"/projects/{pid}/share-links", json={"role": "viewer"})
    assert link.status_code == 201
    token = link.json()["url_path"].removeprefix("/share/")

    shared = await guest.get(f"/shares/{token}")
    assert shared.status_code == 200
    assert shared.json()["role"] == "viewer"
    assert shared.json()["detail"]["access"] == "viewer"
    xml = await guest.get(f"/shares/{token}/versions/{ids['version']}/xml")
    assert xml.status_code == 200
    # Версия чужого проекта по этой ссылке недоступна.
    demo_version = (await owner.get(f"/projects/{DEMO}")).json()["latest_version"]["id"]
    assert (await guest.get(f"/shares/{token}/versions/{demo_version}/xml")).status_code == 404

    # Токен — не пропуск к обычным маршрутам проекта.
    assert (await guest.get(f"/projects/{pid}")).status_code == 401
    assert (await other.get(f"/projects/{pid}")).status_code == 404
    assert (await other.post(f"/shares/{token}/accept")).status_code == 403
    assert (await other.get(f"/projects/{pid}")).status_code == 404

    # Редакторская ссылка гостю данных не открывает.
    invite = await owner.post(f"/projects/{pid}/share-links", json={"role": "editor"})
    invite_token = invite.json()["url_path"].removeprefix("/share/")
    assert (await guest.get(f"/shares/{invite_token}")).status_code == 401
    assert (
        await guest.get(f"/shares/{invite_token}/versions/{ids['version']}/xml")
    ).status_code == 401
    assert (await guest.post(f"/shares/{invite_token}/accept")).status_code == 401

    # Отзыв закрывает ссылку (404), список ссылок не содержит токена.
    listed = (await owner.get(f"/projects/{pid}/share-links")).json()
    assert {item["role"] for item in listed} == {"viewer", "editor"}
    assert token not in str(listed)
    assert (
        await owner.delete(f"/projects/{pid}/share-links/{link.json()['id']}")
    ).status_code == 204
    assert (await guest.get(f"/shares/{token}")).status_code == 404


async def test_expired_link_returns_410_and_expiry_limits(stack: Stack) -> None:
    owner = await stack.user("expiry@example.com")
    guest = await stack.guest()
    pid = (await owner.post("/projects", json={"title": "Срок"})).json()["id"]

    def days(body: dict[str, Any]) -> Any:
        return owner.post(f"/projects/{pid}/share-links", json=body)

    viewer = (await days({"role": "viewer"})).json()
    editor = (await days({"role": "editor"})).json()
    for created, expected in ((viewer, 30), (editor, 7)):
        lifetime = datetime.fromisoformat(created["expires_at"]) - datetime.fromisoformat(
            created["created_at"]
        )
        assert lifetime == timedelta(days=expected)

    assert (await days({"role": "editor", "expires_in_days": 30})).status_code == 201
    too_long = await days({"role": "editor", "expires_in_days": 31})
    assert too_long.status_code == 422
    assert "30" in too_long.json()["detail"]
    assert (await days({"role": "viewer", "expires_in_days": 365})).status_code == 201
    assert (await days({"role": "viewer", "expires_in_days": 366})).status_code == 422
    assert (await days({"role": "viewer", "expires_in_days": 0})).status_code == 422

    token = viewer["url_path"].removeprefix("/share/")
    assert (await guest.get(f"/shares/{token}")).status_code == 200
    past = datetime.now(UTC) - timedelta(days=1)
    async with stack.database.sessions.begin() as session:
        await session.execute(
            update(ProjectShareLinkRow)
            .where(ProjectShareLinkRow.id == UUID(viewer["id"]))
            .values(created_at=past - timedelta(days=1), expires_at=past)
        )
    expired = await guest.get(f"/shares/{token}")
    assert expired.status_code == 410
    assert expired.json() == {"detail": "Срок действия ссылки истёк"}


# ---------- XML ----------


async def test_xml_is_served_as_inert_attachment(stack: Stack) -> None:
    owner = await stack.user("xml@example.com")
    guest = await stack.guest()
    ids = await _finished_project(owner)
    link = await owner.post(f"/projects/{ids['project']}/share-links", json={"role": "viewer"})
    token = link.json()["url_path"].removeprefix("/share/")

    for response in (
        await owner.get(f"/versions/{ids['version']}/xml"),
        await guest.get(f"/shares/{token}/versions/{ids['version']}/xml"),
    ):
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/xml")
        assert response.headers["content-disposition"].startswith('attachment; filename="')
        assert ".bpmn" in response.headers["content-disposition"]
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["content-security-policy"] == "default-src 'none'; sandbox"
        assert response.text == ids["xml"]


MALICIOUS_XML = {
    "xhtml-script": (
        '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">'
        '<bpmn:process id="p"/><html:script xmlns:html="http://www.w3.org/1999/xhtml">'
        "alert(1)</html:script></bpmn:definitions>"
    ),
    "foreign-attribute": (
        '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
        'xmlns:x="http://evil.example/ns" x:onload="alert(1)"><bpmn:process id="p"/>'
        "</bpmn:definitions>"
    ),
    "processing-instruction": (
        '<?xml version="1.0"?><?xml-stylesheet href="http://evil.example/x.xsl"?>'
        '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">'
        '<bpmn:process id="p"/></bpmn:definitions>'
    ),
    "entity": (
        '<?xml version="1.0"?><!DOCTYPE d [<!ENTITY e SYSTEM "file:///etc/passwd">]>'
        '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" name="&e;">'
        '<bpmn:process id="p"/></bpmn:definitions>'
    ),
}


async def test_manual_save_rejects_malicious_xml(stack: Stack) -> None:
    owner = await stack.user("editor-xml@example.com")
    ids = await _finished_project(owner)
    path = f"/projects/{ids['project']}/diagram"

    for name, xml in MALICIOUS_XML.items():
        response = await owner.put(path, json={"xml": xml})
        assert response.status_code == 422, (name, response.text)
        assert response.json()["detail"], name

    # Допустимое содержимое не режем: `bpmn:script` внутри scriptTask — часть стандарта.
    script_task = (
        '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">'
        '<bpmn:process id="p"><bpmn:scriptTask id="t"><bpmn:script>x = 1</bpmn:script>'
        "</bpmn:scriptTask></bpmn:process></bpmn:definitions>"
    )
    allowed = await owner.put(path, json={"xml": script_task})
    assert allowed.status_code == 201, allowed.text

    # Не навредили: версий не прибавилось, а корректный XML (в т.ч. bpmn-js) сохраняется.
    versions = (await owner.get(f"/projects/{ids['project']}/versions")).json()
    ok = await owner.put(path, json={"xml": ids["xml"]})
    assert ok.status_code == 201, ok.text
    assert (
        len((await owner.get(f"/projects/{ids['project']}/versions")).json()) == len(versions) + 1
    )


# ---------- миграция 0006 ----------


async def test_migration_0006_closes_non_seed_projects() -> None:
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
    foreign = uuid4()
    insert = text(
        "INSERT INTO projects (id, title, created_at, updated_at, public_read_only) "
        "VALUES (:id, 't', now(), now(), true)"
    )

    def migrate(sync_connection: Any, revision: str) -> None:
        config.attributes["connection"] = sync_connection
        command.upgrade(config, revision)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(migrate, "0005_auth_and_sharing")
            await connection.execute(insert, {"id": DEMO_PROJECT_ID})
            await connection.execute(insert, {"id": foreign})
            await connection.run_sync(migrate, "head")
            result = await connection.execute(text("SELECT id, public_read_only FROM projects"))
            rows = {row[0]: row[1] for row in result}
        assert rows == {DEMO_PROJECT_ID: True, foreign: False}
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


async def test_container_exposes_database_replacement() -> None:
    """`build_container(database=...)` подставляет готовое подключение вместо DATABASE_URL."""
    settings = Settings(database_url=None, seed_demo_data=False, auth_enabled=True)
    marker = Database("postgresql+asyncpg://u:p@localhost:1/none")
    try:
        container = build_container(settings, database=marker)
        assert container.database is marker
        assert container.access.repo is container.repos.access
        assert replace(container, database=None).database is None
    finally:
        await marker.dispose()
