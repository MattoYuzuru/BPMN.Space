"""Схемы источников."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.domain.models import SourceKind, SourceStatus


class Source(ApiModel):
    id: UUID
    project_id: UUID
    kind: SourceKind
    title: str
    content: str = Field(description="Извлечённый текст; аналитик может его поправить")
    file_name: str | None = None
    mime: str | None = None
    size_bytes: int | None = None
    duration_sec: float | None = Field(default=None, description="Длительность голосовой заметки")
    status: SourceStatus
    active: bool = Field(description="Выключенный источник не участвует в прогонах")
    question_id: UUID | None = Field(
        default=None, description="Для `kind=answer` — вопрос, на который это ответ"
    )
    error: str | None = Field(default=None, description="Причина для `status=failed`")
    created_at: datetime


class SourceTextCreate(ApiModel):
    """Текст или проверенная аналитиком расшифровка голоса (после `POST /transcriptions`)."""

    content: str = Field(min_length=1)
    title: str | None = Field(default=None, max_length=200)
    kind: Literal[SourceKind.TEXT, SourceKind.VOICE] = SourceKind.TEXT
    duration_sec: float | None = Field(default=None, ge=0)


class SourceUpdate(ApiModel):
    title: str | None = Field(default=None, max_length=200)
    content: str | None = None
    active: bool | None = None
