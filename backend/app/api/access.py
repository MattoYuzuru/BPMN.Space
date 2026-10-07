"""HTTP-слой проверки прав: гость → 401, чужой проект → 404, роль без права → 403."""

from uuid import UUID

from fastapi import Request

from app.container import Container
from app.domain.access import ProjectRole, ResourceKind, ShareLink
from app.services.auth import UserRow, stream_user
from app.services.errors import (
    DeletedProjectError,
    ForbiddenError,
    GoneError,
    NotFoundError,
    UnauthorizedError,
)

__all__ = [
    "ProjectRole",
    "ResourceKind",
    "ensure_project_access",
    "ensure_resource_access",
    "get_active_share_link",
    "has_stream_project_access",
    "project_roles",
    "require_account",
]


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
) -> ProjectRole:
    """Скрывать чужие проекты как 404 и запрещать viewer изменяющие запросы."""
    if not request.app.state.auth_enabled:
        return ProjectRole.OWNER
    user_id = require_account(request, user)
    assert user_id is not None  # noqa: S101 — require_account пропускает гостя только без auth
    role = await container.access.project_role(project_id, user_id)
    if role is None:
        if await container.access.project_was_deleted(project_id, user_id):
            raise DeletedProjectError()
        raise NotFoundError("Проект не найден")
    if write and role is ProjectRole.VIEWER:
        raise ForbiddenError("Для изменения проекта нужны права редактора")
    return role


async def project_roles(
    request: Request, container: Container, project_ids: list[UUID], user: UserRow | None
) -> dict[UUID, ProjectRole]:
    """Роль для каждой карточки списка; без auth стенд однопользовательский — всё своё."""
    if not request.app.state.auth_enabled:
        return dict.fromkeys(project_ids, ProjectRole.OWNER)
    return await container.access.project_roles(project_ids, user.id if user else None)


async def ensure_resource_access(
    request: Request,
    container: Container,
    resource_id: UUID,
    user: UserRow | None,
    *,
    resource: ResourceKind,
    write: bool,
) -> ProjectRole:
    """Проверить доступ через проект-владелец объекта."""
    if not request.app.state.auth_enabled:
        return ProjectRole.OWNER
    require_account(request, user)
    project_id = await container.access.resource_project_id(resource, resource_id)
    return await ensure_project_access(request, container, project_id, user, write=write)


async def get_active_share_link(container: Container, token: str) -> ShareLink:
    return await container.access.active_link(token)


async def has_stream_project_access(
    request: Request, container: Container, project_id: UUID, user: UserRow | None
) -> bool:
    """После SSE-handshake проверять и членство, и исходную cookie-сессию.

    У уже начатого ответа нельзя поменять HTTP-статус: потеря доступа закрывает поток
    до отправки следующего события, без исключения и утечки данных из очереди.
    """
    current = await stream_user(request) if request.app.state.auth_enabled else user
    if request.app.state.auth_enabled and (
        current is None or user is None or current.id != user.id
    ):
        return False
    try:
        await ensure_project_access(request, container, project_id, current, write=False)
    except (NotFoundError, GoneError, ForbiddenError, UnauthorizedError):
        return False
    return True
