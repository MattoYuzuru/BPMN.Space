"""HTTP-слой проверки прав: гость → 401, чужой проект → 404, роль без права → 403."""

from typing import Any
from uuid import UUID

from fastapi import Depends, Request

from app.container import Container
from app.domain.access import ProjectRole, ResourceKind, ShareLink
from app.domain.api_tokens import ApiScope, TokenPolicy
from app.services.api_tokens import (
    current_api_token,
    scope_denied_message,
    token_policy_marker,
)
from app.services.auth import UserRow, stream_user
from app.services.errors import (
    DeletedProjectError,
    ForbiddenError,
    GoneError,
    NotFoundError,
    UnauthorizedError,
)

__all__ = [
    "ApiScope",
    "ProjectRole",
    "ResourceKind",
    "ensure_project_access",
    "ensure_resource_access",
    "get_active_share_link",
    "has_stream_project_access",
    "is_review_token",
    "project_roles",
    "require_account",
    "require_scope",
    "require_token_scope",
    "review_lane_ids",
    "token_project_ids",
]


def require_scope(scope: ApiScope | None, *, all_projects: bool = False) -> Any:
    """Объявить право, нужное маршруту при входе по токену доступа (RFC-0007).

    Подключается в `dependencies=[...]` маршрута. Cookie-сессию не ограничивает: там решает
    роль в проекте. Проверку выполняет аутентификация по токену (`services/auth.token_user`):
    маршрут без объявления по токену недоступен (`403`), так что новые маршруты закрыты по
    умолчанию. `scope=None` — достаточно любого действующего токена.

    Ставьте в декоратор маршрута (или `APIRouter(dependencies=[...])` — она входит в сам
    маршрут). Пометка в `include_router(dependencies=[...])` не попадает в `route.dependant`
    исходного маршрута и не учитывается: такой маршрут по токену остаётся закрытым
    (`tests/test_api_tokens.py`).
    """
    return Depends(token_policy_marker(TokenPolicy(scope, all_projects=all_projects)))


def require_token_scope(request: Request, scope: ApiScope) -> None:
    """Дополнительное право, которое зависит от тела запроса (например, медиафайл ведёт к
    платной расшифровке). Cookie-сессию не ограничивает."""
    token = current_api_token(request)
    if token is not None and not token.has_scope(scope):
        raise ForbiddenError(scope_denied_message(scope))


def token_project_ids(request: Request) -> frozenset[UUID] | None:
    """Проекты, которыми ограничен токен запроса; None — без ограничения (или cookie)."""
    token = current_api_token(request)
    if token is None or token.project_ids is None:
        return None
    return frozenset(token.project_ids)


def is_review_token(request: Request) -> bool:
    """Запрос пришёл по токену проверки, выданному ссылкой reviewer (RFC-0007, шаг 3)."""
    token = current_api_token(request)
    return token is not None and token.is_review()


def review_lane_ids(request: Request) -> tuple[str, ...] | None:
    """Область проверки токена: tuple дорожек (пустой — весь проект) или None вне проверки."""
    token = current_api_token(request)
    if token is None or not token.is_review():
        return None
    return token.lane_ids or ()


def require_account(request: Request, user: UserRow | None) -> UUID | None:
    """При включённой auth гостям — 401; без auth стенд однопользовательский."""
    if request.app.state.auth_enabled and user is None:
        raise UnauthorizedError("Войдите в аккаунт")
    return user.id if user is not None else None


async def ensure_project_access(
    request: Request,
    container: Container,
    project_id: UUID,
    user: UserRow | None,
    *,
    write: bool,
    allow_reviewer: bool = False,
) -> ProjectRole:
    """Скрывать чужие проекты как 404 и запрещать роли без права изменяющие запросы.

    Токен проверки (RFC-0007, шаг 3) даёт псевдо-роль `REVIEWER`: чтение проекта и — только с
    `allow_reviewer=True` — ответы на вопросы области. Смену проекта, источников и схемы
    запрещает. Живость ссылки проверена аутентификацией токена при каждом запросе.
    """
    if not request.app.state.auth_enabled:
        return ProjectRole.OWNER
    token = current_api_token(request)
    review = token is not None and token.is_review()
    if review:
        # У токена проверки нет членства: вход в проект — через проект ссылки.
        assert token is not None  # noqa: S101 — review выводится из токена
        if not token.allows_project(project_id):
            raise NotFoundError("Проект не найден")
        role = ProjectRole.REVIEWER
    else:
        user_id = require_account(request, user)
        assert user_id is not None  # noqa: S101 — без auth роль всегда owner
        if token is not None and not token.allows_project(project_id):
            # Проект вне токена неотличим от чужого: тот же 404, без квитанции об удалении.
            raise NotFoundError("Проект не найден")
        role = await container.access.project_role(project_id, user_id)
        if role is None:
            if await container.access.project_was_deleted(project_id, user_id):
                raise DeletedProjectError()
            raise NotFoundError("Проект не найден")
    if write and role not in {ProjectRole.OWNER, ProjectRole.EDITOR}:
        if role is ProjectRole.REVIEWER and allow_reviewer:
            return role
        if role is ProjectRole.VIEWER:
            raise ForbiddenError("Для изменения проекта нужны права редактора")
        raise ForbiddenError(
            "Ссылка проверки не позволяет менять проект: доступны чтение схемы и ответы "
            "на вопросы выбранных дорожек"
        )
    return role


async def project_roles(
    request: Request, container: Container, project_ids: list[UUID], user: UserRow | None
) -> dict[UUID, ProjectRole]:
    """Роль для каждой карточки списка; без auth стенд однопользовательский — всё своё."""
    if not request.app.state.auth_enabled:
        return dict.fromkeys(project_ids, ProjectRole.OWNER)
    roles = await container.access.project_roles(project_ids, user.id if user else None)
    token = current_api_token(request)
    if token is not None and token.is_review():
        for project_id in project_ids:
            if token.allows_project(project_id):
                roles[project_id] = ProjectRole.REVIEWER
    return roles


async def ensure_resource_access(
    request: Request,
    container: Container,
    resource_id: UUID,
    user: UserRow | None,
    *,
    resource: ResourceKind,
    write: bool,
    allow_reviewer: bool = False,
) -> ProjectRole:
    """Проверить доступ через проект-владелец объекта."""
    if not request.app.state.auth_enabled:
        return ProjectRole.OWNER
    if not is_review_token(request):
        require_account(request, user)
    project_id = await container.access.resource_project_id(resource, resource_id)
    role = await ensure_project_access(
        request, container, project_id, user, write=write, allow_reviewer=allow_reviewer
    )
    if role is ProjectRole.REVIEWER and resource is ResourceKind.RUN:
        # Прогоны содержат вопросы и этапы всего проекта: поток или журнал раскрыл бы
        # проверяющему чужие дорожки. Ссылка проверки даёт схему, вопросы области и ответы.
        raise ForbiddenError(
            "Ссылка проверки не даёт доступа к прогонам: доступны схема, вопросы области и ответы"
        )
    return role


async def get_active_share_link(container: Container, token: str) -> ShareLink:
    return await container.access.active_link(token)


async def has_stream_project_access(
    request: Request, container: Container, project_id: UUID, user: UserRow | None
) -> bool:
    """После SSE-handshake проверять и членство, и исходную cookie-сессию.

    У уже начатого ответа нельзя поменять HTTP-статус: потеря доступа закрывает поток
    до отправки следующего события, без исключения и утечки данных из очереди.
    """
    try:
        current = await stream_user(request) if request.app.state.auth_enabled else user
    except (UnauthorizedError, ForbiddenError):
        return False  # токен доступа отозван или истёк во время потока
    if request.app.state.auth_enabled and (
        current is None or user is None or current.id != user.id
    ):
        return False
    try:
        await ensure_project_access(request, container, project_id, current, write=False)
    except (NotFoundError, GoneError, ForbiddenError, UnauthorizedError):
        return False
    return True
