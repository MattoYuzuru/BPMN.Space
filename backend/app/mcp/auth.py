"""Авторизация MCP-сервера (RFC-0007, шаг 2): токен доступа, права инструментов, проекты.

MCP доступен только по персональному токену `Authorization: Bearer bps_…` из волны 1:
cookie-сессии и CSRF здесь не участвуют — MCP-клиент не браузер. Аутентификация повторяет REST
(`services.auth.token_owner`): неизвестный, отозванный, истёкший токен и токен заблокированного
аккаунта неразличимы (`401`).

Права объявляются таблицей «инструмент → право» (`TOOL_POLICIES`), а не открываются по
умолчанию: инструмент, которого нет в таблице, недоступен (`403`), даже если у токена есть все
права. Роль в проекте (`owner`/`editor`/`viewer`) и ограничение `project_ids` сужают доступ так
же, как в REST: чужой проект — `404`, viewer не меняет проект — `403`.

Проверка выполняется на каждом HTTP-запросе к `/mcp`: middleware находит токен и владельца и
кладёт `McpIdentity` в `scope["mcp_auth"]`; инструменты, ресурсы и подсказки читают его через
`identity_of`. Ответы об ошибках входа не раскрывают, существует ли токен или проект.
"""

from __future__ import annotations

import json
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID

from mcp.server.mcpserver.context import Context
from mcp.server.mcpserver.exceptions import ToolError
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.domain.access import ProjectRole, ResourceKind
from app.domain.api_tokens import ApiScope, ApiToken, hash_secret
from app.services.api_tokens import INVALID_ACCESS_MESSAGE, bearer_secret, scope_denied_message
from app.services.auth import token_owner
from app.services.errors import (
    ConflictError,
    DeletedProjectError,
    ForbiddenError,
    GoneError,
    InvalidInputError,
    NotFoundError,
    PayloadTooLargeError,
    ServiceError,
    UnauthorizedError,
    UnavailableError,
    UnsupportedMediaError,
)

if TYPE_CHECKING:
    from app.container import Container

__all__ = [
    "INVALID_ACCESS_MESSAGE",
    "McpAuthMiddleware",
    "McpIdentity",
    "ToolPolicy",
    "as_tool_error",
    "begin_operation",
    "begin_tool",
    "ensure_project",
    "ensure_resource",
    "identity_of",
    "prompt_policy",
    "resource_policy",
    "tool_policy",
]

#: Ключ в ASGI-scope, куда middleware кладёт проверенного владельца токена.
MCP_AUTH_KEY = "mcp_auth"
_WWW_AUTH = (b"www-authenticate", b'Bearer realm="bpmn-space"')
_JSON_HEADERS = (
    (b"content-type", b"application/json; charset=utf-8"),
    (b"x-content-type-options", b"nosniff"),
)


@dataclass(frozen=True, slots=True)
class ToolPolicy:
    """Что нужно для вызова инструмента: право токена и признак «дорогого» вызова."""

    scope: ApiScope
    expensive: bool = False
    all_projects: bool = False


#: Таблица «инструмент → право» (RFC-0007). Инструмента вне таблицы по токену не существует:
#: новая регистрация без строки здесь остаётся закрытой (проверяет `tests/test_mcp.py`).
TOOL_POLICIES: dict[str, ToolPolicy] = {
    "list_projects": ToolPolicy(ApiScope.PROJECTS_READ),
    "get_project": ToolPolicy(ApiScope.PROJECTS_READ),
    "create_project": ToolPolicy(ApiScope.PROJECTS_WRITE, all_projects=True),
    "list_sources": ToolPolicy(ApiScope.PROJECTS_READ),
    "read_source": ToolPolicy(ApiScope.PROJECTS_READ),
    "add_source": ToolPolicy(ApiScope.SOURCES_WRITE),
    "update_source": ToolPolicy(ApiScope.SOURCES_WRITE),
    "delete_source": ToolPolicy(ApiScope.SOURCES_DELETE),
    "list_questions": ToolPolicy(ApiScope.PROJECTS_READ),
    "answer_question": ToolPolicy(ApiScope.QUESTIONS_ANSWER),
    "estimate_run": ToolPolicy(ApiScope.RUNS_START),
    "start_run": ToolPolicy(ApiScope.RUNS_START, expensive=True),
    "get_run": ToolPolicy(ApiScope.PROJECTS_READ),
    "get_diagram": ToolPolicy(ApiScope.PROJECTS_READ),
    "check_diagram": ToolPolicy(ApiScope.PROJECTS_READ),
    "save_diagram": ToolPolicy(ApiScope.PROJECTS_WRITE),
}

#: Ресурсы MCP — только чтение; как и инструменты, закрыты по умолчанию.
RESOURCE_POLICIES: dict[str, ApiScope] = {
    "project_diagram": ApiScope.PROJECTS_READ,
    "project_questions": ApiScope.PROJECTS_READ,
}

#: Подсказки MCP — текстовые сценарии для клиента, секретов не отдают; тоже требуют чтения.
PROMPT_POLICIES: dict[str, ApiScope] = {
    "collect_process_materials": ApiScope.PROJECTS_READ,
    "review_my_lane": ApiScope.PROJECTS_READ,
}


@dataclass(frozen=True, slots=True)
class McpIdentity:
    """Проверенный владелец токена, от чьего имени выполняются вызовы MCP."""

    container: Container
    token: ApiToken
    user: Any  # services.auth.UserRow; Any — чтобы не тянуть SQLAlchemy-типы в представление
    expensive: TokenRateLimiter | None = None

    @property
    def token_hash(self) -> str:
        return hash_secret(self.token.token_hash)


def tool_policy(name: str) -> ToolPolicy:
    policy = TOOL_POLICIES.get(name)
    if policy is None:
        raise ForbiddenError(
            "Этот инструмент не разрешён по токену доступа: обновите токен или клиент MCP"
        )
    return policy


def resource_policy(name: str) -> ApiScope:
    scope = RESOURCE_POLICIES.get(name)
    if scope is None:
        raise ForbiddenError("Этот ресурс недоступен по токену доступа")
    return scope


def prompt_policy(name: str) -> ApiScope:
    scope = PROMPT_POLICIES.get(name)
    if scope is None:
        raise ForbiddenError("Эта подсказка недоступна по токену доступа")
    return scope


@dataclass(slots=True)
class TokenRateLimiter:
    """Скользящее окно на токен для дорогих вызовов MCP: свои таблица и ключи.

    Общий лимит `/api/v1` на IP не покрывает `/mcp`; здесь считаем по хешу токена, чтобы
    агент не обходил бюджет владельца сменой IP. Значения щедрые (как у «дорогих» вызовов REST).
    """

    limit: int
    window: float = 60.0
    clock: Callable[[], float] = time.monotonic
    _hits: OrderedDict[str, deque[float]] = field(default_factory=OrderedDict[str, deque[float]])
    _max_keys: int = 10_000

    def check(self, key: str) -> float | None:
        """Записать событие. `None` — можно; иначе секунды до освобождения слота."""
        now = self.clock()
        horizon = now - self.window
        hits = self._hits.get(key)
        if hits is None:
            if len(self._hits) >= self._max_keys:
                self._hits.popitem(last=False)
            hits = self._hits[key] = deque()
        else:
            self._hits.move_to_end(key)
        while hits and hits[0] <= horizon:
            hits.popleft()
        if len(hits) >= self.limit:
            return max(hits[0] + self.window - now, 0.0)
        hits.append(now)
        return None


async def _send_json(
    send: Send,
    status: int,
    payload: dict[str, Any],
    *,
    headers: tuple[tuple[bytes, bytes], ...] = (),
) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    response_headers = [*_JSON_HEADERS, *headers]
    response_headers.append((b"content-length", str(len(body)).encode("ascii")))
    await send({"type": "http.response.start", "status": status, "headers": response_headers})
    await send({"type": "http.response.body", "body": body})


_STATUS_BY_ERROR: tuple[tuple[type[ServiceError], int], ...] = (
    (UnauthorizedError, 401),
    (ForbiddenError, 403),
    (NotFoundError, 404),
    (GoneError, 410),
    (ConflictError, 409),
    (PayloadTooLargeError, 413),
    (UnsupportedMediaError, 415),
    (InvalidInputError, 422),
    (UnavailableError, 503),
)


def error_status(error: ServiceError) -> int:
    """HTTP-статус той же ошибки сервиса, что и в REST (`app/api/errors.py`)."""
    return next(
        (status for error_type, status in _STATUS_BY_ERROR if isinstance(error, error_type)), 400
    )


def as_tool_error(error: ServiceError) -> ToolError:
    """Ошибка сервиса → ожидаемая ошибка инструмента MCP: сообщение увидит модель.

    Тексты сервисов уже на русском и без ключей, внутренних адресов и тел ответов провайдеров;
    коды REST (`401`/`403`/`404`) в MCP не передаются отдельным полем — модель видит причину.
    """
    return ToolError(error.message)


class McpAuthMiddleware:
    """ASGI-middleware `/mcp`: проверяет Bearer-токен и кладёт владельца в scope.

    Аутентификация — как в REST: неизвестный, отозванный, истёкший токен и токен заблокированного
    аккаунта дают одинаковый `401`; база недоступна — `503`. Прочие запросы (без заголовка) —
    тоже `401`, чтобы клиент не решил, что сервер публичный.
    """

    def __init__(self, app: ASGIApp, container: Container, *, expensive_limit: int) -> None:
        self._app = app
        self._container = container
        self._limiter = TokenRateLimiter(expensive_limit) if expensive_limit > 0 else None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] == "OPTIONS":
            await self._app(scope, receive, send)
            return
        request = Request(scope)
        secret = bearer_secret(request)
        try:
            owner = (
                await token_owner(self._container.api_tokens, self._container.database, secret)
                if secret is not None
                else None
            )
        except ServiceError as error:
            await _send_json(send, error_status(error), {"detail": error.message})
            return
        except Exception:
            await _send_json(send, 503, {"detail": "Сервис доступа временно недоступен"})
            return
        if owner is None:
            await _send_json(send, 401, {"detail": INVALID_ACCESS_MESSAGE}, headers=(_WWW_AUTH,))
            return
        token, user = owner
        identity = McpIdentity(self._container, token, user, self._limiter)
        child = dict(scope)
        child[MCP_AUTH_KEY] = identity
        await self._app(child, receive, send)


def identity_of(ctx: Context[Any, Any]) -> McpIdentity:
    """Проверенный владелец токена текущего запроса MCP."""
    request = ctx.request_context.request
    identity = getattr(request, "scope", {}).get(MCP_AUTH_KEY) if request is not None else None
    if not isinstance(identity, McpIdentity):
        raise ToolError("Требуется действующий токен доступа: вход в MCP только по Bearer-токену")
    return identity


def begin_operation(ctx: Context[Any, Any], scope: ApiScope) -> McpIdentity:
    """Проверить право ресурса/подсказки (у инструментов таблица и лимит — `begin_tool`)."""
    identity = identity_of(ctx)
    if not identity.token.has_scope(scope):
        raise ToolError(scope_denied_message(scope))
    return identity


def begin_tool(ctx: Context[Any, Any], name: str) -> McpIdentity:
    """Право инструмента по таблице; закрыто по умолчанию; лимит частоты для дорогих вызовов."""
    policy = tool_policy(name)
    identity = identity_of(ctx)
    if not identity.token.has_scope(policy.scope):
        raise ToolError(scope_denied_message(policy.scope))
    if policy.all_projects and identity.token.project_ids is not None:
        raise ToolError(
            "Токен ограничен выбранными проектами и не может создавать новые: "
            "создайте токен для всех проектов в Настройках → «Доступ для агентов»"
        )
    if policy.expensive and identity.expensive is not None:
        retry = identity.expensive.check(identity.token_hash)
        if retry is not None:
            seconds = max(int(retry) + 1, 1)
            raise ToolError(f"Слишком много дорогих вызовов. Повторите через {seconds} с.")
    return identity


async def ensure_project(identity: McpIdentity, project_id: UUID, *, write: bool) -> ProjectRole:
    """Тот же доступ, что в REST: чужой проект — `404`, viewer на изменение — `403`.

    Токен ограничивает проекты (`project_ids`): проект вне списка неотличим от чужого.
    """
    container = identity.container
    if not identity.token.allows_project(project_id):
        raise NotFoundError("Проект не найден")
    role = await container.access.project_role(project_id, identity.user.id)
    if role is None:
        if await container.access.project_was_deleted(project_id, identity.user.id):
            raise DeletedProjectError()
        raise NotFoundError("Проект не найден")
    if write and role is ProjectRole.VIEWER:
        raise ForbiddenError("Для изменения проекта нужны права редактора")
    return role


async def ensure_resource(
    identity: McpIdentity,
    resource: ResourceKind,
    resource_id: UUID,
    *,
    write: bool,
) -> ProjectRole:
    """Доступ к объекту через проект-владелец: неизвестный объект и чужой проект — `404`."""
    project_id = await identity.container.access.resource_project_id(resource, resource_id)
    return await ensure_project(identity, project_id, write=write)
