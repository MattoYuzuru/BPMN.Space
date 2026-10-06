"""Проверка роли пользователя и срока действия ссылок проекта."""

from datetime import datetime
from hashlib import sha256
from uuid import UUID

from app.domain.access import ProjectRole, ResourceKind, ShareLink
from app.infra.repositories.base import AccessRepository
from app.services.common import Runtime
from app.services.errors import GoneError, NotFoundError, UnavailableError

__all__ = ["AccessService", "ProjectRole", "token_digest"]


def token_digest(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def is_expired(link: ShareLink, now: datetime) -> bool:
    return link.expires_at is not None and link.expires_at <= now


class AccessService:
    """Роли и ссылки. Без PostgreSQL (`repo is None`) любая проверка отвечает 503."""

    def __init__(self, repo: AccessRepository | None, *, runtime: Runtime) -> None:
        self._repo = repo
        self._rt = runtime

    @property
    def repo(self) -> AccessRepository:
        if self._repo is None:
            raise UnavailableError("Для аккаунтов и общего доступа требуется PostgreSQL")
        return self._repo

    async def project_role(self, project_id: UUID, user_id: UUID) -> ProjectRole | None:
        return await self.repo.project_role(project_id, user_id)

    async def project_roles(
        self, project_ids: list[UUID], user_id: UUID | None
    ) -> dict[UUID, ProjectRole]:
        return await self.repo.project_roles(project_ids, user_id)

    async def resource_project_id(self, kind: ResourceKind, resource_id: UUID) -> UUID:
        project_id = await self.repo.resource_project_id(kind, resource_id)
        if project_id is None:
            raise NotFoundError("Объект не найден")
        return project_id

    async def active_link(self, token: str) -> ShareLink:
        """Живая ссылка по сырому токену: неизвестная или отозванная — 404, истёкшая — 410."""
        link = await self.repo.find_share_link(token_digest(token))
        if link is None or link.revoked_at is not None:
            raise NotFoundError("Ссылка не найдена или отключена")
        if is_expired(link, self._rt.clock()):
            raise GoneError("Срок действия ссылки истёк")
        return link

    async def active_link_by_id(self, link_id: UUID) -> ShareLink:
        """Перепроверить доступ уже открытой гостевой realtime-сессии после отзыва ссылки."""
        link = await self.repo.get_share_link(link_id)
        if link is None or link.revoked_at is not None or is_expired(link, self._rt.clock()):
            raise NotFoundError("Ссылка не найдена или отключена")
        return link
