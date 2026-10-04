"""Доступ к проектам: роли, члены проекта и ссылки-приглашения."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class ProjectRole(StrEnum):
    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"


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
    """Ссылка доступа. Сырой токен не хранится — только его SHA-256."""

    id: UUID
    project_id: UUID
    role: str
    token_hash: str
    created_by: UUID
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ProjectMember:
    user_id: UUID
    email: str
    role: str
    added_at: datetime
