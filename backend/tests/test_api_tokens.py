"""Токены доступа без PostgreSQL: модель, сервис на in-memory хранилище, политики маршрутов.

HTTP-сценарии с настоящей аутентификацией — `tests/test_api_tokens_http.py` (PostgreSQL).
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.routing import APIRoute, _iter_routes_with_context
from starlette.requests import Request

from app.api.access import require_scope
from app.config import Settings
from app.domain.api_tokens import (
    DEFAULT_SCOPES,
    MAX_ACTIVE_TOKENS_PER_USER,
    TOKEN_PREFIX,
    ApiScope,
    ApiToken,
    display_prefix,
    hash_secret,
    looks_like_secret,
)
from app.infra.repositories.memory import InMemoryStore
from app.main import create_app
from app.services.api_tokens import (
    ApiTokenService,
    bearer_secret,
    check_route_policy,
    route_token_policy,
)
from app.services.auth import optional_user, required_user, stream_user
from app.services.common import Runtime
from app.services.errors import (
    ConflictError,
    ForbiddenError,
    InvalidInputError,
    NotFoundError,
    UnavailableError,
)

USER = uuid4()
OTHER = uuid4()


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


async def _allow(_: UUID) -> bool:
    return True


async def _deny(_: UUID) -> bool:
    return False


def _service() -> tuple[ApiTokenService, InMemoryStore, Clock]:
    store = InMemoryStore()
    clock = Clock()
    return ApiTokenService(store.repositories(), runtime=Runtime(clock=clock)), store, clock


async def _create(service: ApiTokenService, **overrides: Any) -> tuple[ApiToken, str]:
    params: dict[str, Any] = {
        "name": "Claude Code на ноутбуке",
        "scopes": None,
        "project_ids": None,
        "expires_in_days": None,
        "can_access": _allow,
        **overrides,
    }
    return await service.create(USER, **params)


def test_secret_format_hash_and_prefix() -> None:
    secret = TOKEN_PREFIX + "a" * 43
    assert looks_like_secret(secret)
    assert not looks_like_secret("bps_short")
    assert not looks_like_secret("ghp_" + "a" * 43)
    assert not looks_like_secret(TOKEN_PREFIX + "a" * 200)
    assert len(hash_secret(secret)) == 64
    assert display_prefix(secret) == "bps_aaaaaa"


async def test_create_stores_only_hash_with_defaults() -> None:
    service, store, clock = _service()

    token, secret = await _create(service, name="  Claude   Code  ")

    assert secret.startswith(TOKEN_PREFIX)
    assert looks_like_secret(secret)
    stored = store.api_tokens[token.id]
    assert stored.token_hash == hash_secret(secret)
    assert secret not in repr(stored)
    assert stored.token_prefix == secret[:10]
    assert stored.name == "Claude Code"
    assert stored.scopes == DEFAULT_SCOPES
    assert stored.project_ids is None
    assert stored.expires_at == clock.now + timedelta(days=30)
    assert [item.id for item in await service.list_for(USER)] == [token.id]
    assert await service.list_for(OTHER) == []


async def test_create_validates_input() -> None:
    service, _, _ = _service()
    with pytest.raises(InvalidInputError):
        await _create(service, name="   ")
    with pytest.raises(InvalidInputError):
        await _create(service, scopes=[])
    with pytest.raises(InvalidInputError):
        await _create(service, expires_in_days=366)
    with pytest.raises(InvalidInputError):
        await _create(service, expires_in_days=0)
    with pytest.raises(InvalidInputError):
        await _create(service, project_ids=[])
    with pytest.raises(InvalidInputError):
        await _create(service, project_ids=[uuid4() for _ in range(101)])
    with pytest.raises(NotFoundError):
        await _create(service, project_ids=[uuid4()], can_access=_deny)


async def test_create_orders_scopes_and_deduplicates_projects() -> None:
    service, _, _ = _service()
    project = uuid4()
    token, _ = await _create(
        service,
        scopes=[ApiScope.RUNS_START, ApiScope.PROJECTS_READ, ApiScope.RUNS_START],
        project_ids=[project, project],
        expires_in_days=365,
    )
    assert token.scopes == (ApiScope.PROJECTS_READ, ApiScope.RUNS_START)
    assert token.project_ids == (project,)
    assert token.allows_project(project)
    assert not token.allows_project(uuid4())


async def test_active_token_limit_counts_only_active() -> None:
    service, _, clock = _service()
    for _ in range(MAX_ACTIVE_TOKENS_PER_USER):
        await _create(service, expires_in_days=1)
    with pytest.raises(ConflictError):
        await _create(service)
    clock.now += timedelta(days=2)  # все истекли и больше не занимают лимит
    await _create(service)


async def test_authenticate_rejects_unknown_revoked_and_expired() -> None:
    service, _, clock = _service()
    token, secret = await _create(service, expires_in_days=7)

    assert await service.authenticate(secret) is not None
    assert await service.authenticate(secret + "x") is None
    assert await service.authenticate("not-a-token") is None

    clock.now += timedelta(days=7)
    assert await service.authenticate(secret) is None

    fresh, fresh_secret = await _create(service)
    await service.revoke(USER, fresh.id)
    assert await service.authenticate(fresh_secret) is None
    assert [item.id for item in await service.list_for(USER)] == [token.id]


async def test_revoke_only_own_active_token() -> None:
    service, _, _ = _service()
    token, _ = await _create(service)
    with pytest.raises(NotFoundError):
        await service.revoke(OTHER, token.id)
    with pytest.raises(NotFoundError):
        await service.revoke(USER, uuid4())
    await service.revoke(USER, token.id)
    with pytest.raises(NotFoundError):
        await service.revoke(USER, token.id)


async def test_last_used_is_written_at_most_once_a_minute() -> None:
    service, store, clock = _service()
    token, secret = await _create(service)

    await service.authenticate(secret)
    first = store.api_tokens[token.id].last_used_at
    assert first == clock.now

    clock.now += timedelta(seconds=30)
    await service.authenticate(secret)
    assert store.api_tokens[token.id].last_used_at == first

    clock.now += timedelta(seconds=31)
    await service.authenticate(secret)
    assert store.api_tokens[token.id].last_used_at == clock.now


async def test_service_without_repository_is_unavailable() -> None:
    store = InMemoryStore()
    service = ApiTokenService(replace(store.repositories(), api_tokens=None), runtime=Runtime())
    with pytest.raises(UnavailableError):
        await service.list_for(USER)


def _request(headers: dict[str, str], route: Any = None) -> Request:
    scope: dict[str, Any] = {
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }
    if route is not None:
        scope["route"] = route
    return Request(scope)


def test_bearer_secret_parsing() -> None:
    assert bearer_secret(_request({})) is None
    assert bearer_secret(_request({"Authorization": "Basic abc"})) is None
    assert bearer_secret(_request({"Authorization": "Bearer bps_abc"})) == "bps_abc"
    assert bearer_secret(_request({"Authorization": "bearer   bps_abc "})) == "bps_abc"
    assert bearer_secret(_request({"Authorization": "Bearer"})) == ""


def _token(**overrides: Any) -> ApiToken:
    now = datetime(2026, 11, 4, tzinfo=UTC)
    values: dict[str, Any] = {
        "id": uuid4(),
        "user_id": USER,
        "name": "t",
        "token_prefix": "bps_aaaaaa",
        "token_hash": "0" * 64,
        "scopes": DEFAULT_SCOPES,
        "project_ids": None,
        "expires_at": now + timedelta(days=1),
        "created_at": now,
        **overrides,
    }
    return ApiToken(**values)


def test_route_policy_denies_by_default_and_checks_scope() -> None:
    router = APIRouter()

    @router.get("/open", dependencies=[require_scope(None)])
    async def open_route() -> None: ...

    @router.post("/write", dependencies=[require_scope(ApiScope.SOURCES_WRITE)])
    async def write_route() -> None: ...

    @router.post(
        "/create", dependencies=[require_scope(ApiScope.PROJECTS_WRITE, all_projects=True)]
    )
    async def create_route() -> None: ...

    @router.delete("/closed")
    async def closed_route() -> None: ...

    routes = {route.path: route for route in router.routes if isinstance(route, APIRoute)}
    token = _token()
    check_route_policy(_request({}, routes["/open"]), token)
    with pytest.raises(ForbiddenError, match="sources:write"):
        check_route_policy(_request({}, routes["/write"]), token)
    check_route_policy(_request({}, routes["/write"]), _token(scopes=(ApiScope.SOURCES_WRITE,)))
    with pytest.raises(ForbiddenError, match="недоступно по токену"):
        check_route_policy(_request({}, routes["/closed"]), token)
    with pytest.raises(ForbiddenError, match="недоступно по токену"):
        check_route_policy(_request({}), token)
    full = _token(scopes=tuple(ApiScope))
    check_route_policy(_request({}, routes["/create"]), full)
    with pytest.raises(ForbiddenError, match="выбранными проектами"):
        check_route_policy(
            _request({}, routes["/create"]), _token(scopes=tuple(ApiScope), project_ids=(uuid4(),))
        )
    # Кэш на маршруте не меняет ответа при повторном вызове.
    assert route_token_policy(routes["/write"]) == route_token_policy(routes["/write"])
    assert route_token_policy(None) == ()


# Маршруты, доступные по токену, и нужные им права (RFC-0007). Новый маршрут без объявления
# по токену закрыт; этот список фиксирует, что открыто осознанно.
EXPECTED_POLICIES: dict[tuple[str, str], str] = {
    ("GET", "/api/v1/projects"): "projects:read",
    ("POST", "/api/v1/projects"): "projects:write+all",
    ("POST", "/api/v1/projects/from-example"): "projects:write+all",
    ("GET", "/api/v1/projects/{project_id}"): "projects:read",
    ("PATCH", "/api/v1/projects/{project_id}"): "projects:write",
    ("POST", "/api/v1/projects/{project_id}/sources/text"): "sources:write",
    ("POST", "/api/v1/projects/{project_id}/sources/file"): "sources:write",
    ("POST", "/api/v1/projects/{project_id}/sources/sample"): "sources:write",
    ("POST", "/api/v1/projects/{project_id}/sources/media/estimate"): "projects:read",
    ("GET", "/api/v1/sources/{source_id}/media"): "projects:read",
    ("GET", "/api/v1/sources/{source_id}/segments"): "projects:read",
    ("POST", "/api/v1/sources/{source_id}/ocr"): "sources:write",
    ("PATCH", "/api/v1/sources/{source_id}"): "sources:write",
    ("DELETE", "/api/v1/sources/{source_id}"): "sources:delete",
    ("POST", "/api/v1/transcriptions"): "runs:start",
    ("GET", "/api/v1/projects/{project_id}/questions"): "projects:read",
    ("GET", "/api/v1/projects/{project_id}/agent-activity"): "projects:read",
    ("POST", "/api/v1/questions/{question_id}/answer"): "questions:answer",
    ("POST", "/api/v1/questions/{question_id}/actions"): "questions:answer",
    ("POST", "/api/v1/questions/{question_id}/ignore"): "questions:answer",
    ("POST", "/api/v1/questions/{question_id}/reopen"): "questions:answer",
    ("POST", "/api/v1/projects/{project_id}/runs"): "runs:start",
    ("POST", "/api/v1/projects/{project_id}/runs/estimate"): "projects:read",
    ("GET", "/api/v1/runs/{run_id}"): "projects:read",
    ("POST", "/api/v1/runs/{run_id}/cancel"): "runs:start",
    ("POST", "/api/v1/runs/{run_id}/resume"): "runs:start",
    ("GET", "/api/v1/runs/{run_id}/events"): "projects:read",
    ("GET", "/api/v1/projects/{project_id}/versions"): "projects:read",
    ("POST", "/api/v1/projects/{project_id}/versions/{version_id}/checkpoint"): "projects:write",
    ("GET", "/api/v1/versions/{version_id}"): "projects:read",
    ("GET", "/api/v1/versions/{version_id}/xml"): "projects:read",
    ("PUT", "/api/v1/projects/{project_id}/diagram"): "projects:write",
    ("POST", "/api/v1/projects/{project_id}/assistant"): "runs:start",
    ("POST", "/api/v1/assistant/chat"): "runs:start",
    ("GET", "/api/v1/auth/me"): "any",
    ("GET", "/api/v1/auth/session"): "any",
}


def test_token_policies_of_application_routes() -> None:
    app = create_app(Settings(database_url=None, app_env="test", seed_demo_data=False))
    declared: dict[tuple[str, str], str] = {}
    for route, context in _iter_routes_with_context(app.router.routes):
        if not isinstance(route, APIRoute):
            continue
        policies = route_token_policy(route)
        if not policies:
            continue
        path = context.path_format if context else route.path
        for method in route.methods or ():
            declared[(method, path)] = ",".join(
                (policy.scope.value if policy.scope else "any")
                + ("+all" if policy.all_projects else "")
                for policy in policies
            )
    assert declared == EXPECTED_POLICIES
    # Управление токенами, ключами, ссылками, участниками и удаление проекта — только cookie.
    closed = {
        ("GET", "/api/v1/me/api-tokens"),
        ("POST", "/api/v1/me/api-tokens"),
        ("GET", "/api/v1/me/llm-credentials"),
        ("POST", "/api/v1/projects/{project_id}/share-links"),
        ("DELETE", "/api/v1/projects/{project_id}"),
        ("DELETE", "/api/v1/projects/{project_id}/members/{member_id}"),
    }
    assert not closed & declared.keys()


def test_require_scope_is_dependency_marker() -> None:
    marker = require_scope(ApiScope.PROJECTS_READ)
    assert isinstance(marker, type(Depends(lambda: None)))
    assert marker.dependency() is None


def test_scope_marker_on_include_router_is_ignored() -> None:
    """Пометка в `include_router(dependencies=…)` не попадает в дерево исходного маршрута и не
    открывает его; пометка в `APIRouter(dependencies=…)` входит в сам маршрут и учитывается."""
    inner = APIRouter()

    @inner.get("/inner")
    async def inner_route() -> None: ...

    outer = APIRouter(dependencies=[require_scope(ApiScope.PROJECTS_READ)])

    @outer.get("/outer")
    async def outer_route() -> None: ...

    app = FastAPI()
    app.include_router(inner, dependencies=[require_scope(ApiScope.PROJECTS_READ)])
    app.include_router(outer)
    routes = {
        route.path: route
        for route, _ in _iter_routes_with_context(app.router.routes)
        if isinstance(route, APIRoute)
    }
    full = _token(scopes=tuple(ApiScope))
    assert route_token_policy(routes["/inner"]) == ()
    with pytest.raises(ForbiddenError, match="недоступно по токену"):
        check_route_policy(_request({}, routes["/inner"]), full)
    check_route_policy(_request({}, routes["/outer"]), full)


def _calls(dependant: Any) -> list[Any]:
    found = [dependant.call]
    for child in dependant.dependencies:
        found.extend(_calls(child))
    return found


# Маршруты без пользователя: публичные данные или вход по паролю.
PUBLIC_ROUTES = {
    ("GET", "/api/v1/examples"),
    ("GET", "/api/v1/samples"),
    ("GET", "/api/v1/auth/csrf"),
    ("POST", "/api/v1/auth/session/login"),
    ("POST", "/api/v1/auth/register"),
    ("GET", "/health"),
}
# Маршруты FastAPI Users, которые читают cookie своей зависимостью, а не `optional_user`.
# Заголовок `Authorization` на них отклоняет middleware (`main.py`), CSRF обязателен.
COOKIE_ONLY_ROUTES = {("POST", "/api/v1/auth/session/logout")}


def test_every_authenticating_route_goes_through_optional_or_stream_user() -> None:
    """Обход дерева зависимостей всех маршрутов: пользователь определяется только через
    `optional_user`/`required_user`/`stream_user` (там проверяется токен), иначе маршрут явно
    в белом списке. Маршрут с пометкой права обязан определять пользователя."""
    app = create_app(Settings(database_url=None, app_env="test", seed_demo_data=False))
    entry_points = {optional_user, required_user, stream_user}
    seen: set[tuple[str, str]] = set()
    for route, context in _iter_routes_with_context(app.router.routes):
        if not isinstance(route, APIRoute):
            continue
        path = context.path_format if context else route.path
        calls = _calls(route.dependant)
        via_entry = any(call in entry_points for call in calls)
        library_auth = any(
            getattr(call, "__name__", "").startswith("current_user") for call in calls
        )
        for method in route.methods or ():
            key = (method, path)
            seen.add(key)
            if route_token_policy(route):
                assert via_entry, f"{key}: право объявлено, но пользователь не определяется"
            if via_entry:
                continue
            if library_auth:
                assert key in COOKIE_ONLY_ROUTES, f"{key}: cookie FastAPI Users в обход токена"
            else:
                assert key in PUBLIC_ROUTES, f"{key}: маршрут не определяет пользователя"
    assert seen >= PUBLIC_ROUTES | COOKIE_ONLY_ROUTES
