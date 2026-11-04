"""Схемы источников."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import ConfigDict, Field

from app.api.schemas.common import ApiModel
from app.domain.models import SourceKind, SourceOrigin, SourceStatus, SourceTrust


class SourceDerivation(ApiModel):
    """Как получен производный источник (RFC-0006)."""

    capability: str = Field(description="Возможность: `speech_to_text`, `ocr`, `vision`…")
    provider: str = Field(description="Реализация, которая ответила: `deepgram`, `mock`…")
    model: str | None = Field(default=None, description="Модель провайдера, если известна")
    params: dict[str, Any] = Field(
        default_factory=dict[str, Any], description="Параметры обработки (сегменты, язык…)"
    )
    cost_usd: float | None = Field(default=None, description="Стоимость, если провайдер её сообщил")
    created_at: datetime


class MediaInfo(ApiModel):
    """Дорожки записи по `ffprobe`; `null` — неизвестно (сервер без ffmpeg)."""

    has_audio: bool | None = None
    has_video: bool | None = None


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
    warning: str | None = Field(
        default=None,
        description="Для `status=ready`: источник прочитан не полностью (см. `unreadable_pages`)",
    )
    unreadable_pages: list[int] = Field(
        default_factory=list[int],
        description="Номера страниц PDF без текстового слоя (сканы): их текст не извлечён",
    )
    created_at: datetime
    origin: SourceOrigin = Field(
        default=SourceOrigin.USER,
        description="`user` — загрузил человек, `derived` — получен из `parent_id`, "
        "`agent` — внешний агент, `answer` — ответ на вопрос",
    )
    parent_id: UUID | None = Field(
        default=None,
        description="Исходный источник того же проекта; дерево строится по этому полю. "
        "Удаление родителя удаляет производные",
    )
    derivation: SourceDerivation | None = Field(
        default=None, description="Для `origin=derived`: возможность, провайдер, модель"
    )
    trust: SourceTrust = Field(
        default=SourceTrust.PRIMARY,
        description="Уровень доверия: `summary` не идёт в контекст модели и в основания",
    )
    edited_by_human: bool = Field(
        default=False, description="Текст производного источника поправил человек"
    )
    media: MediaInfo | None = Field(
        default=None, description="Для записи: есть ли звук и видео. Текст записи — в потомке"
    )


class SourceTextCreate(ApiModel):
    """Текст или проверенная аналитиком расшифровка голоса (после `POST /transcriptions`).

    Лишние поля отклоняются: `parent_id`, `origin`, `trust` вручную не задаются — производные
    источники создаёт только сервер.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    content: str = Field(min_length=1)
    title: str | None = Field(default=None, max_length=200)
    kind: Literal[SourceKind.TEXT, SourceKind.VOICE] = SourceKind.TEXT
    duration_sec: float | None = Field(default=None, ge=0)


class SourceUpdate(ApiModel):
    title: str | None = Field(default=None, max_length=200)
    content: str | None = None
    active: bool | None = None
