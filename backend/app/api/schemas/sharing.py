"""Контракты доступа по ссылке и ролям проекта."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.api.schemas.projects import ProjectDetail


class ShareRole(StrEnum):
    VIEWER = "viewer"
    EDITOR = "editor"


class ShareLinkCreate(ApiModel):
    role: ShareRole
    expires_in_days: int | None = Field(
        default=None,
        ge=0,
        le=365,
        description=(
            "Срок ссылки в днях: 7, 30, 365 (год) или 0 (без срока). Для совместимости "
            "null/пропуск выбирает 30 дней. Одинаковые варианты доступны для viewer и editor."
        ),
    )


class ShareLinkCreated(ApiModel):
    id: UUID
    role: ShareRole
    url_path: str = Field(description="Одноразово возвращаемый путь с секретом ссылки")
    created_at: datetime
    expires_at: datetime | None


class ShareLinkRead(ApiModel):
    id: UUID
    role: ShareRole
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None


class SharedProject(ApiModel):
    role: ShareRole
    editor_requires_account: bool
    detail: ProjectDetail


class ShareAccepted(ApiModel):
    project_id: UUID
    role: ShareRole


class ProjectMemberRead(ApiModel):
    user_id: UUID
    email: str
    role: ShareRole
    added_at: datetime
