"""Проверка роли пользователя и срока действия ссылок проекта."""

from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select

from app.infra.database import Database
from app.infra.db_models import (
    DiagramVersionRow,
    ProjectMemberRow,
    ProjectRow,
    ProjectShareLinkRow,
    QuestionRow,
    RunRow,
    SourceRow,
)


class ProjectRole(StrEnum):
    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"


def token_digest(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


async def get_project_role(
    database: Database, project_id: UUID, user_id: UUID
) -> ProjectRole | None:
    async with database.sessions() as session:
        project = await session.get(ProjectRow, project_id)
        if project is None:
            return None
        if project.owner_id == user_id:
            return ProjectRole.OWNER
        membership = await session.get(ProjectMemberRow, (project_id, user_id))
        if membership is not None and membership.role == ProjectRole.EDITOR:
            return ProjectRole.EDITOR
        return ProjectRole.VIEWER if project.public_read_only else None


async def get_project_roles(
    database: Database, project_ids: list[UUID], user_id: UUID | None
) -> dict[UUID, ProjectRole]:
    """Роли пользователя для страницы проектов двумя запросами вместо запроса на проект."""
    if not project_ids:
        return {}
    async with database.sessions() as session:
        projects = (
            await session.execute(
                select(ProjectRow.id, ProjectRow.owner_id, ProjectRow.public_read_only).where(
                    ProjectRow.id.in_(project_ids)
                )
            )
        ).all()
        editable: set[UUID] = set()
        if user_id is not None:
            editable = set(
                await session.scalars(
                    select(ProjectMemberRow.project_id).where(
                        ProjectMemberRow.project_id.in_(project_ids),
                        ProjectMemberRow.user_id == user_id,
                        ProjectMemberRow.role == ProjectRole.EDITOR,
                    )
                )
            )
    roles: dict[UUID, ProjectRole] = {}
    for project_id, owner_id, public in projects:
        if user_id is not None and owner_id == user_id:
            roles[project_id] = ProjectRole.OWNER
        elif project_id in editable:
            roles[project_id] = ProjectRole.EDITOR
        elif public:
            roles[project_id] = ProjectRole.VIEWER
    return roles


async def get_resource_project_id(
    database: Database, resource_id: UUID, resource: str
) -> UUID | None:
    models = {
        "source": SourceRow,
        "question": QuestionRow,
        "run": RunRow,
        "version": DiagramVersionRow,
    }
    row_type = models[resource]
    async with database.sessions() as session:
        return await session.scalar(select(row_type.project_id).where(row_type.id == resource_id))


async def get_share_link(database: Database, token: str) -> tuple[ProjectShareLinkRow | None, bool]:
    async with database.sessions() as session:
        link = await session.scalar(
            select(ProjectShareLinkRow).where(ProjectShareLinkRow.token_hash == token_digest(token))
        )
        if link is None or link.revoked_at is not None:
            return None, False
        if link.expires_at is not None and link.expires_at <= datetime.now(UTC):
            return None, True
        return link, False
