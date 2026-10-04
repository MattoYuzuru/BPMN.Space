"""Хранение участников и управление ссылками доступа к проекту."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.infra.database import Database
from app.infra.db_models import ProjectMemberRow, ProjectShareLinkRow, UserRow
from app.services.access import ProjectRole, token_digest


async def list_members(database: Database, project_id: UUID) -> list[tuple[ProjectMemberRow, str]]:
    async with database.sessions() as session:
        rows = (
            await session.execute(
                select(ProjectMemberRow, UserRow)
                .join(
                    UserRow,
                    UserRow.__table__.c.id == ProjectMemberRow.__table__.c.user_id,
                )
                .where(ProjectMemberRow.project_id == project_id)
                .order_by(ProjectMemberRow.added_at)
            )
        ).all()
    return [(member, user.email) for member, user in rows]


async def remove_member(database: Database, project_id: UUID, user_id: UUID) -> bool:
    async with database.sessions.begin() as session:
        result = await session.execute(
            delete(ProjectMemberRow)
            .where(
                ProjectMemberRow.project_id == project_id,
                ProjectMemberRow.user_id == user_id,
            )
            .returning(ProjectMemberRow.user_id)
        )
        return result.scalar_one_or_none() is not None


async def create_share_link(
    database: Database,
    *,
    project_id: UUID,
    raw_token: str,
    role: str,
    created_by: UUID,
    created_at: datetime,
    expires_at: datetime | None,
) -> UUID:
    link_id = uuid4()
    row = ProjectShareLinkRow(
        id=link_id,
        project_id=project_id,
        token_hash=token_digest(raw_token),
        role=role,
        created_by=created_by,
        created_at=created_at,
        expires_at=expires_at,
    )
    async with database.sessions.begin() as session:
        session.add(row)
    return link_id


async def list_share_links(database: Database, project_id: UUID) -> list[ProjectShareLinkRow]:
    async with database.sessions() as session:
        return list(
            (
                await session.scalars(
                    select(ProjectShareLinkRow)
                    .where(ProjectShareLinkRow.project_id == project_id)
                    .order_by(ProjectShareLinkRow.created_at.desc())
                )
            ).all()
        )


async def revoke_share_link(
    database: Database, project_id: UUID, link_id: UUID, revoked_at: datetime
) -> bool:
    async with database.sessions.begin() as session:
        link = await session.scalar(
            select(ProjectShareLinkRow).where(
                ProjectShareLinkRow.id == link_id,
                ProjectShareLinkRow.project_id == project_id,
            )
        )
        if link is None:
            return False
        if link.revoked_at is None:
            link.revoked_at = revoked_at
    return True


async def accept_editor_invite(
    database: Database, project_id: UUID, user_id: UUID, added_at: datetime
) -> None:
    async with database.sessions.begin() as session:
        await session.execute(
            insert(ProjectMemberRow)
            .values(
                project_id=project_id,
                user_id=user_id,
                role=ProjectRole.EDITOR.value,
                added_at=added_at,
            )
            .on_conflict_do_update(
                index_elements=[ProjectMemberRow.project_id, ProjectMemberRow.user_id],
                set_={"role": ProjectRole.EDITOR.value},
            )
        )
