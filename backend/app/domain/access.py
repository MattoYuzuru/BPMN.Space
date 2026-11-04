"""Доступ к проектам: роли, члены проекта и ссылки-приглашения."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from uuid import UUID


class ProjectRole(StrEnum):
    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"
    # Псевдо-роль доступа по ссылке проверки (RFC-0007, шаг 3): не членство в проекте,
    # а ограниченное чтение и ответы на вопросы своей области. В БД роли участников её нет.
    REVIEWER = "reviewer"


class ShareRole(StrEnum):
    """Роль ссылки доступа: чтение, приглашение редактора или проверка коллеги."""

    VIEWER = "viewer"
    EDITOR = "editor"
    REVIEWER = "reviewer"


class ProjectScope(StrEnum):
    """Какие проекты показывать: все доступные, свои, принятые общие, демо-примеры."""

    ALL = "all"
    OWN = "own"
    SHARED = "shared"
    EXAMPLES = "examples"


class ResourceKind(StrEnum):
    """Объекты, доступ к которым определяется через проект-владелец."""

    SOURCE = "source"
    QUESTION = "question"
    RUN = "run"
    VERSION = "version"


@dataclass(frozen=True, slots=True)
class ShareLink:
    """Ссылка доступа. Сырой токен не хранится — только его SHA-256.

    У ссылки проверки (role=reviewer) есть область — выбранные дорожки (`lane_ids`): читать
    и отвечать можно только по ним. Пустая область — весь проект.
    """

    id: UUID
    project_id: UUID
    role: str
    token_hash: str
    created_by: UUID
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None = None
    lane_ids: tuple[str, ...] = ()

    def is_review(self) -> bool:
        return self.role == ShareRole.REVIEWER.value


@dataclass(frozen=True, slots=True)
class ProjectMember:
    user_id: UUID
    email: str
    role: str
    added_at: datetime


def project_deletion_key(project_id: UUID, user_id: UUID) -> str:
    """Непрозрачная квитанция: сообщение об удалении только бывшему участнику."""
    return sha256(f"project:{project_id}:user:{user_id}".encode()).hexdigest()


def share_deletion_key(token_hash: str) -> str:
    """Квитанция для обладателя действовавшей ссылки, без сохранения сырого токена."""
    return sha256(f"share:{token_hash}".encode()).hexdigest()
