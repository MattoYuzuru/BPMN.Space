"""SQL-реализация доступа: роли, участники проекта и ссылки-приглашения."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import case, delete, select
from sqlalchemy.dialects.postgresql import insert

from app.domain.access import ProjectMember, ProjectRole, ResourceKind, ShareLink
from app.infra.db_models import (
    DeletedProjectAccessRow,
    DiagramVersionRow,
    ProjectMemberRow,
    ProjectRow,
    ProjectShareLinkRow,
    QuestionRow,
    RunRow,
    SourceRow,
    UserRow,
)
from app.infra.repositories.base import AccessLinkUnavailableError, AccessProjectMissingError
from app.infra.repositories.session import SessionFactory

users = UserRow.__table__  # `email` и `id` у FastAPI Users объявлены без Mapped-типов

_RESOURCE_ROWS = {
    ResourceKind.SOURCE: SourceRow,
    ResourceKind.QUESTION: QuestionRow,
    ResourceKind.RUN: RunRow,
    ResourceKind.VERSION: DiagramVersionRow,
}


def _link(row: ProjectShareLinkRow) -> ShareLink:
    return ShareLink(
        id=row.id,
        project_id=row.project_id,
        role=row.role,
        token_hash=row.token_hash,
        created_by=row.created_by,
        created_at=row.created_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
    )


class SqlAccessRepository:
    def __init__(self, sessions: SessionFactory) -> None:
        self.sessions = sessions

    async def project_role(self, project_id: UUID, user_id: UUID) -> ProjectRole | None:
        async with self.sessions() as session:
            project = await session.get(ProjectRow, project_id)
            if project is None:
                return None
            if project.owner_id == user_id:
                return ProjectRole.OWNER
            membership = await session.get(ProjectMemberRow, (project_id, user_id))
            if membership is not None:
                return ProjectRole(membership.role)
            return ProjectRole.VIEWER if project.public_read_only else None

    async def project_roles(
        self, project_ids: list[UUID], user_id: UUID | None
    ) -> dict[UUID, ProjectRole]:
        if not project_ids:
            return {}
        async with self.sessions() as session:
            projects = (
                await session.execute(
                    select(ProjectRow.id, ProjectRow.owner_id, ProjectRow.public_read_only).where(
                        ProjectRow.id.in_(project_ids)
                    )
                )
            ).all()
            memberships: dict[UUID, ProjectRole] = {}
            if user_id is not None:
                rows = (
                    await session.execute(
                        select(ProjectMemberRow.project_id, ProjectMemberRow.role).where(
                            ProjectMemberRow.project_id.in_(project_ids),
                            ProjectMemberRow.user_id == user_id,
                        )
                    )
                ).all()
                memberships = {project_id: ProjectRole(role) for project_id, role in rows}
        roles: dict[UUID, ProjectRole] = {}
        for project_id, owner_id, public in projects:
            if user_id is not None and owner_id == user_id:
                roles[project_id] = ProjectRole.OWNER
            elif project_id in memberships:
                roles[project_id] = memberships[project_id]
            elif public:
                roles[project_id] = ProjectRole.VIEWER
        return roles

    async def resource_project_id(self, kind: ResourceKind, resource_id: UUID) -> UUID | None:
        row_type = _RESOURCE_ROWS[kind]
        async with self.sessions() as session:
            return await session.scalar(
                select(row_type.project_id).where(row_type.id == resource_id)
            )

    async def deleted_access(self, key_hash: str) -> bool:
        async with self.sessions() as session:
            row = await session.get(DeletedProjectAccessRow, key_hash)
            return row is not None and row.expires_at > datetime.now(UTC)

    async def find_share_link(self, token_hash: str) -> ShareLink | None:
        async with self.sessions() as session:
            row = await session.scalar(
                select(ProjectShareLinkRow).where(ProjectShareLinkRow.token_hash == token_hash)
            )
            return _link(row) if row else None

    async def get_share_link(self, link_id: UUID) -> ShareLink | None:
        async with self.sessions() as session:
            row = await session.get(ProjectShareLinkRow, link_id)
            return _link(row) if row else None

    async def add_share_link(self, link: ShareLink) -> None:
        async with self.sessions.begin() as session:
            project = await session.scalar(
                select(ProjectRow).where(ProjectRow.id == link.project_id).with_for_update()
            )
            if project is None:
                raise AccessProjectMissingError
            session.add(
                ProjectShareLinkRow(
                    id=link.id,
                    project_id=link.project_id,
                    token_hash=link.token_hash,
                    role=link.role,
                    created_by=link.created_by,
                    created_at=link.created_at,
                    expires_at=link.expires_at,
                )
            )

    async def list_share_links(self, project_id: UUID) -> list[ShareLink]:
        async with self.sessions() as session:
            rows = await session.scalars(
                select(ProjectShareLinkRow)
                .where(ProjectShareLinkRow.project_id == project_id)
                .order_by(ProjectShareLinkRow.created_at.desc())
            )
            return [_link(row) for row in rows]

    async def revoke_share_link(
        self, project_id: UUID, link_id: UUID, revoked_at: datetime
    ) -> bool:
        async with self.sessions.begin() as session:
            await session.scalar(
                select(ProjectRow).where(ProjectRow.id == project_id).with_for_update()
            )
            row = await session.scalar(
                select(ProjectShareLinkRow).where(
                    ProjectShareLinkRow.id == link_id,
                    ProjectShareLinkRow.project_id == project_id,
                )
            )
            if row is None:
                return False
            if row.revoked_at is None:
                row.revoked_at = revoked_at
        return True

    async def list_members(self, project_id: UUID) -> list[ProjectMember]:
        async with self.sessions() as session:
            rows = (
                await session.execute(
                    select(ProjectMemberRow, users.c.email)
                    .join(users, users.c.id == ProjectMemberRow.user_id)
                    .where(ProjectMemberRow.project_id == project_id)
                    .order_by(ProjectMemberRow.added_at)
                )
            ).all()
        return [
            ProjectMember(
                user_id=member.user_id, email=email, role=member.role, added_at=member.added_at
            )
            for member, email in rows
        ]

    async def remove_member(self, project_id: UUID, user_id: UUID) -> bool:
        async with self.sessions.begin() as session:
            # Общая блокировка с удалением проекта и принятием приглашения.
            project = await session.scalar(
                select(ProjectRow).where(ProjectRow.id == project_id).with_for_update()
            )
            if project is None:
                return False
            result = await session.execute(
                delete(ProjectMemberRow)
                .where(
                    ProjectMemberRow.project_id == project_id,
                    ProjectMemberRow.user_id == user_id,
                )
                .returning(ProjectMemberRow.user_id)
            )
            return result.scalar_one_or_none() is not None

    async def add_member(
        self,
        project_id: UUID,
        user_id: UUID,
        role: ProjectRole,
        added_at: datetime,
        *,
        link_id: UUID | None = None,
    ) -> None:
        async with self.sessions.begin() as session:
            project = await session.scalar(
                select(ProjectRow).where(ProjectRow.id == project_id).with_for_update()
            )
            if project is None:
                raise AccessProjectMissingError
            if link_id is not None:
                link = await session.get(ProjectShareLinkRow, link_id)
                if link is None or link.project_id != project_id or link.revoked_at is not None:
                    raise AccessLinkUnavailableError(expired=False)
                if link.expires_at is not None and link.expires_at <= datetime.now(UTC):
                    raise AccessLinkUnavailableError(expired=True)
            if project.owner_id == user_id:
                return
            await session.execute(
                insert(ProjectMemberRow)
                .values(
                    project_id=project_id,
                    user_id=user_id,
                    role=role.value,
                    added_at=added_at,
                )
                .on_conflict_do_update(
                    index_elements=[ProjectMemberRow.project_id, ProjectMemberRow.user_id],
                    set_={
                        "role": case(
                            (
                                ProjectMemberRow.role == ProjectRole.EDITOR.value,
                                ProjectRole.EDITOR.value,
                            ),
                            else_=role.value,
                        )
                    },
                )
            )
