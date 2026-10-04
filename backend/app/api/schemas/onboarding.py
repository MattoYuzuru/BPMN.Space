"""Схемы онбординга: тур, чек-лист «Начало работы», место для пункта и учебные материалы."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.domain.onboarding import (
    ChecklistItem,
    ItemSource,
    TargetHint,
    TargetRoute,
    TourStatus,
    TourStepKey,
)
from app.fixtures.samples import SampleKind


class TourState(ApiModel):
    status: TourStatus
    step: TourStepKey | None = Field(description="Ключ текущего шага; null вне тура")
    project_id: UUID | None = Field(description="Учебный проект пользователя")
    updated_at: datetime = Field(description="Последнее изменение (смена шага — для длительности)")


class ChecklistEntry(ApiModel):
    key: ChecklistItem
    completed_at: datetime
    source: ItemSource


class ChecklistState(ApiModel):
    hidden: bool = Field(description="Плашка и чек-лист скрыты пользователем")
    items: list[ChecklistEntry] = Field(description="Отмеченные пункты по времени отметки")


class OnboardingState(ApiModel):
    """Всегда `200`: без аккаунтов, без входа и при `ONBOARDING_ENABLED=false` — `enabled=false`
    и пустые остальные поля."""

    enabled: bool
    tour: TourState | None = None
    checklist: ChecklistState | None = None
    tour_text_suggestion: str | None = Field(
        default=None, description="Текст-подсказка для шага тура «Опишите процесс»"
    )


class TourUpdate(ApiModel):
    """Смена шага или статуса тура. Не переданные поля не меняются;
    `project_id: null` снимает учебный проект."""

    status: TourStatus | None = None
    step: TourStepKey | None = None
    project_id: UUID | None = None


class ChecklistUpdate(ApiModel):
    hidden: bool


class OnboardingEvent(ApiModel):
    item: ChecklistItem = Field(description="Только `simulation_run` и `diagram_exported`")


class OnboardingTarget(ApiModel):
    """Куда вести по пункту. Якорь и тексты подсказок выбирает фронтенд по `item` и `hint`."""

    route: TargetRoute
    project_id: UUID | None = None
    question_id: UUID | None = Field(
        default=None, description="Самый ранний открытый вопрос (для пунктов про вопросы)"
    )
    hint: TargetHint


class Sample(ApiModel):
    id: str
    title: str = Field(description="Для документа — имя файла с расширением")
    kind: SampleKind
    format: str = Field(description="docx, md, txt или voice")
    size_bytes: int = Field(description="Размер файла или текста расшифровки")
    tour: bool = Field(description="Документ, на котором строится тур")


class SampleAdd(ApiModel):
    sample_id: str = Field(min_length=1, max_length=100)
