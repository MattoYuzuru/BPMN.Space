"""Персональные токены доступа (RFC-0007, шаг 1): выпуск, список, отзыв, проверка секрета.

Открытый секрет существует только в ответе `create`; в хранилище — SHA-256. Проверка по
`Authorization: Bearer` не различает «неизвестный», «отозванный» и «истёкший» токены: для
клиента это один ответ `401`.

Права проверяются по маршруту: зависимость-маркер `token_policy_marker` (её подключает
`app.api.access.require_scope`) несёт `TokenPolicy`, а аутентификация по токену находит её в
дереве зависимостей сопоставленного маршрута. Маршрут без маркера по токену недоступен.
"""

from collections.abc import Awaitable, Callable, Iterable
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from starlette.requests import HTTPConnection

from app.domain.api_tokens import (
    DEFAULT_SCOPES,
    DEFAULT_TTL_DAYS,
    LAST_USED_RESOLUTION,
    MAX_ACTIVE_TOKENS_PER_USER,
    MAX_NAME_CHARS,
    MAX_PROJECTS_PER_TOKEN,
    MAX_TTL_DAYS,
    SCOPE_LABELS,
    ApiScope,
    ApiToken,
    TokenPolicy,
    display_prefix,
    generate_secret,
    hash_secret,
    looks_like_secret,
    ordered_scopes,
)
from app.infra.repositories.base import ApiTokenRepository, Repositories
from app.services.common import Runtime
from app.services.errors import (
    ConflictError,
    ForbiddenError,
    InvalidInputError,
    NotFoundError,
    UnavailableError,
)

__all__ = [
    "INVALID_ACCESS_MESSAGE",
    "ApiTokenService",
    "bearer_secret",
    "check_route_policy",
    "current_api_token",
    "route_token_policy",
    "token_policy_marker",
]

INVALID_ACCESS_MESSAGE = "Токен доступа недействителен: проверьте его или создайте новый"
_POLICY_ATTR = "__api_token_policy__"
_STATE_ATTR = "api_token"


class ApiTokenService:
    def __init__(self, repos: Repositories, *, runtime: Runtime) -> None:
        self._repos = repos
        self._rt = runtime

    @property
    def _repo(self) -> ApiTokenRepository:
        repo = self._repos.api_tokens
        if repo is None:
            raise UnavailableError("Токены доступа требуют PostgreSQL")
        return repo

    def now(self) -> datetime:
        return self._rt.clock()

    async def list_for(self, user_id: UUID) -> list[ApiToken]:
        return await self._repo.list_by_user(user_id)

    async def create(
        self,
        user_id: UUID,
        *,
        name: str,
        scopes: Iterable[ApiScope] | None,
        project_ids: Iterable[UUID] | None,
        expires_in_days: int | None,
        can_access: Callable[[UUID], Awaitable[bool]],
    ) -> tuple[ApiToken, str]:
        """Новый токен и его секрет (единственный раз). `can_access` — проверка роли в проекте."""
        title = " ".join(name.split())[:MAX_NAME_CHARS]
        if not title:
            raise InvalidInputError("Укажите название токена")
        chosen = ordered_scopes(scopes if scopes is not None else DEFAULT_SCOPES)
        if not chosen:
            raise InvalidInputError("Выберите хотя бы одно право")
        days = DEFAULT_TTL_DAYS if expires_in_days is None else expires_in_days
        if not 1 <= days <= MAX_TTL_DAYS:
            raise InvalidInputError(f"Срок токена — от 1 до {MAX_TTL_DAYS} дней")
        projects = await self._checked_projects(project_ids, can_access)
        now = self._rt.clock()
        if await self._repo.count_active(user_id, now) >= MAX_ACTIVE_TOKENS_PER_USER:
            raise ConflictError(
                f"Достигнут лимит действующих токенов ({MAX_ACTIVE_TOKENS_PER_USER}): "
                "отзовите ненужные"
            )
        secret = generate_secret()
        token = ApiToken(
            id=self._rt.new_id(),
            user_id=user_id,
            name=title,
            token_prefix=display_prefix(secret),
            token_hash=hash_secret(secret),
            scopes=chosen,
            project_ids=projects,
            expires_at=now + timedelta(days=days),
            created_at=now,
        )
        await self._repo.add(token)
        return token, secret

    @staticmethod
    async def _checked_projects(
        project_ids: Iterable[UUID] | None, can_access: Callable[[UUID], Awaitable[bool]]
    ) -> tuple[UUID, ...] | None:
        if project_ids is None:
            return None
        unique = tuple(dict.fromkeys(project_ids))
        if not unique:
            raise InvalidInputError("Выберите хотя бы один проект или разрешите все проекты")
        if len(unique) > MAX_PROJECTS_PER_TOKEN:
            raise InvalidInputError(f"Не больше {MAX_PROJECTS_PER_TOKEN} проектов в одном токене")
        for project_id in unique:
            if not await can_access(project_id):
                # Как и везде: чужой проект неотличим от несуществующего.
                raise NotFoundError("Проект не найден")
        return unique

    async def revoke(self, user_id: UUID, token_id: UUID) -> None:
        token = await self._repo.get(token_id)
        if token is None or token.user_id != user_id or token.revoked_at is not None:
            raise NotFoundError("Токен не найден")
        await self._repo.revoke(token_id, self._rt.clock())

    async def authenticate(self, secret: str) -> ApiToken | None:
        """Действующий токен по секрету или None; `last_used_at` — не чаще раза в минуту."""
        if not looks_like_secret(secret):
            return None
        token = await self._repo.by_hash(hash_secret(secret))
        now = self._rt.clock()
        if token is None or not token.is_active(now):
            return None
        if token.needs_touch(now):
            await self._repo.touch(token.id, now, older_than=now - LAST_USED_RESOLUTION)
        return token


def bearer_secret(connection: HTTPConnection) -> str | None:
    """Значение `Authorization: Bearer …` или None. Пустое значение — тоже попытка входа."""
    header = connection.headers.get("authorization")
    if header is None:
        return None
    scheme, _, value = header.strip().partition(" ")
    if scheme.lower() != "bearer":
        return None
    return value.strip()


def current_api_token(connection: HTTPConnection) -> ApiToken | None:
    """Токен, которым аутентифицирован запрос; None — cookie-сессия или гость."""
    return getattr(connection.state, _STATE_ATTR, None)


def remember_api_token(connection: HTTPConnection, token: ApiToken) -> None:
    setattr(connection.state, _STATE_ATTR, token)


def token_policy_marker(policy: TokenPolicy) -> Callable[[], None]:
    """Зависимость-маркер без логики: несёт политику маршрута для проверки токена."""

    def api_token_policy() -> None:
        return None

    setattr(api_token_policy, _POLICY_ATTR, policy)
    return api_token_policy


_ROUTE_CACHE_ATTR = "_api_token_policies"


def _collect(dependant: Any, found: list[TokenPolicy]) -> None:
    policy = getattr(dependant.call, _POLICY_ATTR, None)
    if isinstance(policy, TokenPolicy):
        found.append(policy)
    for child in dependant.dependencies:
        _collect(child, found)


def route_token_policy(route: Any) -> tuple[TokenPolicy, ...]:
    """Политики, объявленные у маршрута (FastAPI кладёт его в `scope["route"]`)."""
    if route is None or getattr(route, "dependant", None) is None:
        return ()
    # Кэш на самом маршруте: APIRoute не хешируется, а дерево зависимостей неизменно.
    cached = getattr(route, _ROUTE_CACHE_ATTR, None)
    if cached is None:
        found: list[TokenPolicy] = []
        _collect(route.dependant, found)
        cached = tuple(found)
        setattr(route, _ROUTE_CACHE_ATTR, cached)
    return cached


def check_route_policy(connection: HTTPConnection, token: ApiToken) -> None:
    """403, если маршрут закрыт для токенов или токену не хватает права."""
    policies = route_token_policy(connection.scope.get("route"))
    if not policies:
        raise ForbiddenError(
            "Это действие недоступно по токену доступа: выполните его в браузере под своим "
            "аккаунтом"
        )
    for policy in policies:
        if policy.scope is not None and not token.has_scope(policy.scope):
            raise ForbiddenError(
                f"Токену не хватает права «{policy.scope.value}» "
                f"({SCOPE_LABELS[policy.scope]}). Создайте токен с этим правом в "
                "Настройках → «Доступ для агентов»"
            )
        if policy.all_projects and token.project_ids is not None:
            raise ForbiddenError(
                "Токен ограничен выбранными проектами и не может создавать новые: "
                "нужен токен для всех проектов"
            )
