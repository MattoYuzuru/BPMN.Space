"""Участники проекта и ссылки доступа: создание, отзыв, принятие приглашения."""

import secrets
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from app.domain.access import ProjectMember, ShareLink
from app.services.access import AccessService, token_digest
from app.services.common import Runtime
from app.services.errors import InvalidInputError, NotFoundError

# Срок ссылки в днях: (по умолчанию, максимум). Приглашение редактора живёт недолго,
# потому что даёт запись; ссылка на чтение — безопаснее, поэтому срок длиннее.
EXPIRY_DAYS: dict[str, tuple[int, int]] = {"editor": (7, 30), "viewer": (30, 365)}


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
        default, maximum = EXPIRY_DAYS[role]
        days = default if expires_in_days is None else expires_in_days
        if not 1 <= days <= maximum:
            raise InvalidInputError(f"Срок ссылки с ролью «{role}» — от 1 до {maximum} дней")
        now = self._rt.clock()
        token = secrets.token_urlsafe(32)
        link = ShareLink(
            id=uuid4(),
            project_id=project_id,
            role=role,
            token_hash=token_digest(token),
            created_by=created_by,
            created_at=now,
            expires_at=now + timedelta(days=days),
        )
        await self._access.repo.add_share_link(link)
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

    async def accept_invite(self, project_id: UUID, user_id: UUID) -> None:
        await self._access.repo.add_editor(project_id, user_id, self._rt.clock())
