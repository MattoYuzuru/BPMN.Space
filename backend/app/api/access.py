"""HTTP mapping for project permission checks."""

from uuid import UUID

from fastapi import HTTPException, Request, status

from app.api.auth import UserRow
from app.container import Container
from app.infra.db_models import ProjectShareLinkRow
from app.services.access import ProjectRole, get_project_role, get_project_roles
from app.services.access import get_resource_project_id as resolve_project_id
from app.services.access import get_share_link as resolve_share_link


def require_account(request: Request, user: UserRow | None) -> UUID | None:
    if request.app.state.auth_enabled and user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Войдите в аккаунт")
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
    if container.database is None:
        raise HTTPException(status_code=503, detail="Для доступа к проектам требуется PostgreSQL")
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Войдите в аккаунт")
    role = await get_project_role(container.database, project_id, user.id)
    if role is None:
        raise HTTPException(status_code=404, detail="Проект не найден")
    if write and role is ProjectRole.VIEWER:
        raise HTTPException(status_code=403, detail="Для изменения проекта нужны права редактора")
    return role


async def project_roles(
    request: Request, container: Container, project_ids: list[UUID], user: UserRow | None
) -> dict[UUID, ProjectRole]:
    """Роль для каждой карточки списка; без auth стенд однопользовательский — всё своё."""
    if not request.app.state.auth_enabled or container.database is None:
        return dict.fromkeys(project_ids, ProjectRole.OWNER)
    return await get_project_roles(container.database, project_ids, user.id if user else None)


async def ensure_resource_access(
    request: Request,
    container: Container,
    resource_id: UUID,
    user: UserRow | None,
    *,
    resource: str,
    write: bool,
) -> ProjectRole:
    """Проверить доступ через проект-владелец объекта."""
    if not request.app.state.auth_enabled:
        return ProjectRole.OWNER
    if container.database is None:
        raise HTTPException(status_code=503, detail="Для доступа к проектам требуется PostgreSQL")
    project_id = await resolve_project_id(container.database, resource_id, resource)
    if project_id is None:
        raise HTTPException(status_code=404, detail="Объект не найден")
    return await ensure_project_access(request, container, project_id, user, write=write)


async def get_active_share_link(container: Container, token: str) -> ProjectShareLinkRow:
    if container.database is None:
        raise HTTPException(status_code=503, detail="Для ссылок доступа требуется PostgreSQL")
    link, expired = await resolve_share_link(container.database, token)
    if link is None:
        if expired:
            raise HTTPException(status_code=410, detail="Срок действия ссылки истёк")
        raise HTTPException(status_code=404, detail="Ссылка не найдена или отключена")
    return link
