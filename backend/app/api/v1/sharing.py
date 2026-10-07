"""Участники проекта и ссылки доступа: управление (владелец) и открытие по ссылке."""

from uuid import UUID

from fastapi import APIRouter, Request, Response, status

from app.api.access import ProjectRole, ensure_project_access, get_active_share_link
from app.api.auth import OptionalUserDep
from app.api.deps import ContainerDep
from app.api.responses import bpmn_attachment
from app.api.schemas.common import errors
from app.api.schemas.projects import ProjectDetail as ProjectDetailSchema
from app.api.schemas.sharing import (
    ProjectMemberRead,
    ShareAccepted,
    SharedProject,
    ShareLinkCreate,
    ShareLinkCreated,
    ShareLinkRead,
    ShareRole,
)
from app.container import Container
from app.domain.onboarding import ChecklistItem
from app.services.auth import UserRow
from app.services.errors import ForbiddenError, NotFoundError, UnauthorizedError

router = APIRouter(tags=["sharing"])


async def _ensure_owner(
    request: Request, container: Container, project_id: UUID, user: UserRow | None, message: str
) -> None:
    role = await ensure_project_access(request, container, project_id, user, write=False)
    if role is not ProjectRole.OWNER:
        raise ForbiddenError(message)


@router.get(
    "/projects/{project_id}/members",
    response_model=list[ProjectMemberRead],
    responses=errors(401, 403, 404, 410, 422),
)
async def list_project_members(
    project_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> list[ProjectMemberRead]:
    await _ensure_owner(
        request, container, project_id, user, "Состав участников видит только владелец"
    )
    return [
        ProjectMemberRead(
            user_id=member.user_id,
            email=member.email,
            role=ShareRole(member.role),
            added_at=member.added_at,
        )
        for member in await container.sharing.list_members(project_id)
    ]


@router.delete(
    "/projects/{project_id}/members/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=errors(401, 403, 404, 410, 422),
)
async def remove_project_member(
    project_id: UUID,
    member_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> Response:
    await _ensure_owner(
        request, container, project_id, user, "Участников может удалять только владелец"
    )
    await container.sharing.remove_member(project_id, member_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/projects/{project_id}/membership",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=errors(401, 403, 404, 410, 422),
)
async def leave_project(
    project_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> Response:
    """Выйти из общего проекта; данные владельца и остальных участников сохраняются."""
    await ensure_project_access(request, container, project_id, user, write=False)
    if user is None:
        raise UnauthorizedError("Войдите в аккаунт")
    await container.sharing.leave_project(project_id, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/projects/{project_id}/share-links",
    status_code=status.HTTP_201_CREATED,
    response_model=ShareLinkCreated,
    responses=errors(401, 403, 404, 410, 422),
)
async def create_share_link(
    project_id: UUID,
    body: ShareLinkCreate,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> ShareLinkCreated:
    """Создать ссылку на чтение либо приглашение редактора; сырой токен выдаётся один раз.

    У обеих ролей одинаковый срок: 7, 30, 365 дней или бессрочно (0); по умолчанию 30 дней.
    """
    await _ensure_owner(
        request, container, project_id, user, "Ссылки доступа может создавать только владелец"
    )
    if user is None:  # без аккаунтов владельца нет, ссылки недоступны
        raise UnauthorizedError("Войдите в аккаунт")
    created = await container.sharing.create_link(
        project_id,
        role=body.role.value,
        expires_in_days=body.expires_in_days,
        created_by=user.id,
    )
    await container.onboarding.record(user.id, ChecklistItem.PROJECT_SHARED)
    return ShareLinkCreated(
        id=created.link.id,
        role=body.role,
        url_path=f"/share/{created.token}",
        created_at=created.link.created_at,
        expires_at=created.link.expires_at,
    )


@router.get(
    "/projects/{project_id}/share-links",
    response_model=list[ShareLinkRead],
    responses=errors(401, 403, 404, 410, 422),
)
async def list_share_links(
    project_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> list[ShareLinkRead]:
    await _ensure_owner(request, container, project_id, user, "Списком ссылок управляет владелец")
    return [
        ShareLinkRead(
            id=link.id,
            role=ShareRole(link.role),
            created_at=link.created_at,
            expires_at=link.expires_at,
            revoked_at=link.revoked_at,
        )
        for link in await container.sharing.list_links(project_id)
    ]


@router.delete(
    "/projects/{project_id}/share-links/{link_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=errors(401, 403, 404, 410, 422),
)
async def revoke_share_link(
    project_id: UUID,
    link_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> Response:
    await _ensure_owner(request, container, project_id, user, "Ссылками доступа управляет владелец")
    await container.sharing.revoke_link(project_id, link_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/shares/{token}", response_model=SharedProject, responses=errors(401, 404, 410, 422))
async def read_shared_project(
    token: str,
    container: ContainerDep,
    user: OptionalUserDep,
) -> SharedProject:
    """Открыть проект по ссылке. Ссылка на чтение работает без входа (гостям тоже)."""
    link = await get_active_share_link(container, token)
    role = ShareRole(link.role)
    if role is ShareRole.EDITOR and user is None:
        raise UnauthorizedError("Войдите или зарегистрируйтесь, чтобы открыть проект редактором")
    detail = await container.projects.detail(link.project_id)
    return SharedProject(
        role=role,
        editor_requires_account=role is ShareRole.EDITOR,
        detail=ProjectDetailSchema.of_detail(
            detail, ProjectRole.EDITOR if role is ShareRole.EDITOR else ProjectRole.VIEWER
        ),
    )


@router.get(
    "/shares/{token}/versions/{version_id}/xml",
    response_class=Response,
    responses={
        200: {
            "content": {"application/xml": {}},
            "description": "Диаграмма BPMN по ссылке доступа (вложением)",
        },
        **errors(401, 404, 410, 422),
    },
)
async def download_shared_diagram(
    token: str,
    version_id: UUID,
    container: ContainerDep,
    user: OptionalUserDep,
) -> Response:
    link = await get_active_share_link(container, token)
    if link.role == ShareRole.EDITOR.value and user is None:
        raise UnauthorizedError("Войдите, чтобы открыть ссылку редактора")
    version = await container.versions.get(version_id)
    if version.project_id != link.project_id:
        raise NotFoundError("Версия не относится к этому проекту")
    return bpmn_attachment(version.xml, number=version.number)


@router.post(
    "/shares/{token}/accept",
    response_model=ShareAccepted,
    responses=errors(401, 404, 410, 422),
)
async def accept_share_link(
    token: str,
    container: ContainerDep,
    user: OptionalUserDep,
) -> ShareAccepted:
    link = await get_active_share_link(container, token)
    if user is None:
        raise UnauthorizedError("Войдите или зарегистрируйтесь, чтобы добавить проект в профиль")
    await container.sharing.accept_invite(link.project_id, user.id, link.role, link_id=link.id)
    return ShareAccepted(project_id=link.project_id, role=ShareRole(link.role))
