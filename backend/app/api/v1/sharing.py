"""Google-подобное общее чтение и адресные ссылки на роль проекта."""

import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.access import ProjectRole, ensure_project_access, get_active_share_link
from app.api.auth import OptionalUserDep
from app.api.deps import ContainerDep
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
from app.infra.database import Database
from app.services.sharing import (
    accept_editor_invite as persist_editor_invite,
)
from app.services.sharing import (
    create_share_link as persist_share_link,
)
from app.services.sharing import (
    list_members as get_members,
)
from app.services.sharing import (
    list_share_links as get_share_links,
)
from app.services.sharing import (
    remove_member as delete_member,
)
from app.services.sharing import (
    revoke_share_link as deactivate_share_link,
)

router = APIRouter(tags=["sharing"])


def _database(container: Container) -> Database:
    if container.database is None:
        raise HTTPException(status_code=503, detail="Для ссылок доступа требуется PostgreSQL")
    return container.database


@router.get(
    "/projects/{project_id}/members",
    response_model=list[ProjectMemberRead],
    responses=errors(401, 403, 404, 422),
)
async def list_project_members(
    project_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> list[ProjectMemberRead]:
    role = await ensure_project_access(request, container, project_id, user, write=False)
    if role is not ProjectRole.OWNER:
        raise HTTPException(status_code=403, detail="Состав участников видит только владелец")
    members = await get_members(_database(container), project_id)
    return [
        ProjectMemberRead(
            user_id=member.user_id,
            email=email,
            role=ShareRole(member.role),
            added_at=member.added_at,
        )
        for member, email in members
    ]


@router.delete(
    "/projects/{project_id}/members/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=errors(401, 403, 404, 422),
)
async def remove_project_member(
    project_id: UUID,
    member_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> Response:
    role = await ensure_project_access(request, container, project_id, user, write=False)
    if role is not ProjectRole.OWNER:
        raise HTTPException(status_code=403, detail="Участников может удалять только владелец")
    removed = await delete_member(_database(container), project_id, member_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Участник не найден")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/projects/{project_id}/share-links",
    status_code=status.HTTP_201_CREATED,
    response_model=ShareLinkCreated,
    responses=errors(401, 403, 404, 422),
)
async def create_share_link(
    project_id: UUID,
    body: ShareLinkCreate,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> ShareLinkCreated:
    """Создать ссылку на чтение либо приглашение редактора; сырой токен выдаётся один раз."""
    role = await ensure_project_access(request, container, project_id, user, write=False)
    if role is not ProjectRole.OWNER:
        raise HTTPException(
            status_code=403, detail="Ссылки доступа может создавать только владелец"
        )
    if user is None:
        raise HTTPException(status_code=503, detail="Для ссылок доступа требуется учётная запись")

    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    expires = now + timedelta(days=body.expires_in_days) if body.expires_in_days else None
    link_id = await persist_share_link(
        _database(container),
        project_id=project_id,
        raw_token=token,
        role=body.role.value,
        created_by=user.id,
        created_at=now,
        expires_at=expires,
    )
    return ShareLinkCreated(
        id=link_id,
        role=body.role,
        url_path=f"/share/{token}",
        created_at=now,
        expires_at=expires,
    )


@router.get(
    "/projects/{project_id}/share-links",
    response_model=list[ShareLinkRead],
    responses=errors(401, 403, 404, 422),
)
async def list_share_links(
    project_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> list[ShareLinkRead]:
    role = await ensure_project_access(request, container, project_id, user, write=False)
    if role is not ProjectRole.OWNER:
        raise HTTPException(status_code=403, detail="Списком ссылок управляет владелец")
    rows = await get_share_links(_database(container), project_id)
    return [
        ShareLinkRead(
            id=row.id,
            role=ShareRole(row.role),
            created_at=row.created_at,
            expires_at=row.expires_at,
            revoked_at=row.revoked_at,
        )
        for row in rows
    ]


@router.delete(
    "/projects/{project_id}/share-links/{link_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=errors(401, 403, 404, 422),
)
async def revoke_share_link(
    project_id: UUID,
    link_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> Response:
    role = await ensure_project_access(request, container, project_id, user, write=False)
    if role is not ProjectRole.OWNER:
        raise HTTPException(status_code=403, detail="Ссылками доступа управляет владелец")
    revoked = await deactivate_share_link(
        _database(container),
        project_id,
        link_id,
        datetime.now(UTC),
    )
    if not revoked:
        raise HTTPException(status_code=404, detail="Ссылка не найдена")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/shares/{token}", response_model=SharedProject, responses=errors(401, 404, 410, 422))
async def read_shared_project(
    token: str,
    container: ContainerDep,
    user: OptionalUserDep,
) -> SharedProject:
    link = await get_active_share_link(container, token)
    role = ShareRole(link.role)
    if role is ShareRole.EDITOR and user is None:
        raise HTTPException(
            status_code=401, detail="Войдите или зарегистрируйтесь, чтобы открыть проект редактором"
        )
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
            "description": "Диаграмма BPMN по ссылке доступа",
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
        raise HTTPException(status_code=401, detail="Войдите, чтобы открыть ссылку редактора")
    version = await container.versions.get(version_id)
    if version.project_id != link.project_id:
        raise HTTPException(status_code=404, detail="Версия не относится к этому проекту")
    return Response(content=version.xml, media_type="application/xml")


@router.post(
    "/shares/{token}/accept",
    response_model=ShareAccepted,
    responses=errors(401, 403, 404, 410, 422),
)
async def accept_editor_invite(
    token: str,
    container: ContainerDep,
    user: OptionalUserDep,
) -> ShareAccepted:
    link = await get_active_share_link(container, token)
    if link.role != ShareRole.EDITOR:
        raise HTTPException(status_code=403, detail="Ссылка предназначена только для просмотра")
    if user is None:
        raise HTTPException(
            status_code=401, detail="Войдите или зарегистрируйтесь, чтобы стать редактором"
        )
    await persist_editor_invite(
        _database(container),
        link.project_id,
        user.id,
        datetime.now(UTC),
    )
    return ShareAccepted(project_id=link.project_id)
