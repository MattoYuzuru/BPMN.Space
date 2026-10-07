"""Участники проекта и ссылки доступа: создание, отзыв, принятие приглашения."""

import secrets
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from app.domain.access import ProjectMember, ProjectRole, ShareLink
from app.infra.repositories.base import AccessLinkUnavailableError, AccessProjectMissingError
from app.services.access import AccessService, token_digest
from app.services.common import Runtime
from app.services.errors import (
    DeletedProjectError,
    ForbiddenError,
    GoneError,
    InvalidInputError,
    NotFoundError,
)

# Обе роли используют одни сроки: 7 дней, 30 дней, год или бессрочно (0).
DEFAULT_EXPIRY_DAYS = 30
MAX_EXPIRY_DAYS = 365


@dataclass(frozen=True, slots=True)
class CreatedLink:
    link: ShareLink
    token: str


class SharingService:
    def __init__(self, access: AccessService, *, runtime: Runtime) -> None:
        self._access = access
        self._rt = runtime

    async def create_link(
        self, project_id: UUID, *, role: str, expires_in_days: int | None, created_by: UUID
    ) -> CreatedLink:
        """Новая ссылка; сырой токен возвращается один раз, в БД остаётся его хеш."""
        days = DEFAULT_EXPIRY_DAYS if expires_in_days is None else expires_in_days
        if not 0 <= days <= MAX_EXPIRY_DAYS:
            raise InvalidInputError("Срок ссылки — 0 (без срока) или от 1 до 365 дней")
        now = self._rt.clock()
        token = secrets.token_urlsafe(32)
        link = ShareLink(
            id=uuid4(),
            project_id=project_id,
            role=role,
            token_hash=token_digest(token),
            created_by=created_by,
            created_at=now,
            expires_at=now + timedelta(days=days) if days else None,
        )
        try:
            await self._access.repo.add_share_link(link)
        except AccessProjectMissingError as error:
            raise DeletedProjectError() from error
        return CreatedLink(link=link, token=token)

    async def list_links(self, project_id: UUID) -> list[ShareLink]:
        return await self._access.repo.list_share_links(project_id)

    async def revoke_link(self, project_id: UUID, link_id: UUID) -> None:
        if not await self._access.repo.revoke_share_link(project_id, link_id, self._rt.clock()):
            raise NotFoundError("Ссылка не найдена")

    async def list_members(self, project_id: UUID) -> list[ProjectMember]:
        return await self._access.repo.list_members(project_id)

    async def remove_member(self, project_id: UUID, user_id: UUID) -> None:
        if not await self._access.repo.remove_member(project_id, user_id):
            raise NotFoundError("Участник не найден")

    async def leave_project(self, project_id: UUID, user_id: UUID) -> None:
        """Убрать только своё членство; владелец не может оставить проект без владельца."""
        if await self._access.project_role(project_id, user_id) is ProjectRole.OWNER:
            raise ForbiddenError("Владелец не может выйти из своего проекта; используйте удаление")
        if not await self._access.repo.remove_member(project_id, user_id):
            raise ForbiddenError("Вы не участник этого проекта; общие примеры удалить нельзя")

    async def accept_invite(
        self, project_id: UUID, user_id: UUID, role: str = "editor", *, link_id: UUID | None = None
    ) -> None:
        try:
            await self._access.repo.add_member(
                project_id, user_id, ProjectRole(role), self._rt.clock(), link_id=link_id
            )
        except AccessProjectMissingError as error:
            raise DeletedProjectError() from error
        except AccessLinkUnavailableError as error:
            if error.expired:
                raise GoneError("Срок действия ссылки истёк") from error
            raise NotFoundError("Ссылка не найдена или отключена") from error
