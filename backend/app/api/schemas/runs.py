"""Схемы прогонов и SSE-событий `GET /runs/{id}/events`."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, RootModel, model_validator

from app.api.schemas.common import ApiModel
from app.api.schemas.questions import Question
from app.api.schemas.versions import Version
from app.domain import models
from app.domain.models import RunMode, RunStage, RunStatus
from app.domain.runs import stage_label
from app.llm.capabilities import RunProfile as DomainRunProfile

Effort = Literal["low", "medium", "high", "xhigh", "max"]


class RunProfile(ApiModel):
    """Профиль прогона (RFC-0005). Пусто — умолчания сервера и модели."""

    effort: Effort | None = Field(
        default=None,
        description=(
            "Глубина работы модели: low, medium, high, xhigh, max. Уровень, которого модель "
            "не поддерживает, — 422; у модели без рассуждения поле игнорируется"
        ),
    )
    semantic_review: bool | None = Field(
        default=None, description="Смысловая сверка схемы; null — настройка сервера"
    )

    def to_domain(self) -> DomainRunProfile:
        return DomainRunProfile(effort=self.effort, semantic_review=self.semantic_review)

    @classmethod
    def of(cls, stored: object) -> "RunProfile | None":
        """Профиль из `ir.execution`; у прогонов до RFC-0005 его нет."""
        if not isinstance(stored, dict):
            return None
        return cls.model_validate(DomainRunProfile.from_json(stored).to_json())


class RunSummary(ApiModel):
    """Итог прогона по вопросам («решено 2 · осталось 2 · новых 1»).

    `resolved` — решено этим прогоном; `open` — остались открытыми с прошлых прогонов;
    `new` — новые открытые вопросы этого прогона; `ignored`, `answered` — сколько сейчас.
    """

    resolved: int
    open: int
    new: int
    ignored: int
    answered: int


class QuestionsSummary(ApiModel):
    """Текущее состояние вопросов проекта.

    `resolved` — всего решено; `new` — открытые вопросы, созданные последним завершённым
    прогоном; `open` — остальные открытые («осталось»); `ignored`, `answered` — сколько сейчас.
    """

    resolved: int
    open: int
    new: int
    ignored: int
    answered: int


class Run(ApiModel):
    id: UUID
    project_id: UUID
    mode: RunMode
    status: RunStatus
    stage: RunStage | None = Field(description="Текущий или последний этап; null — в очереди")
    stage_label: str = Field(description="Подпись этапа для интерфейса")
    progress: float = Field(ge=0, le=1)
    started_at: datetime = Field(description="Когда прогон принят")
    finished_at: datetime | None = None
    summary: RunSummary | None = None
    version_id: UUID | None = Field(default=None, description="Версия, собранная прогоном")
    error: str | None = Field(default=None, description="Причина для `status=failed`")
    provider: str | None = Field(
        default=None, description="Провайдер модели: anthropic, openai, openai_compatible, mock"
    )
    model: str | None = Field(default=None, description="Модель, на которой выполнен прогон")
    credential_id: UUID | None = Field(
        default=None, description="Ключ пользователя, с которым запущен прогон; null — сервер"
    )
    profile: RunProfile | None = Field(
        default=None, description="Проверенный профиль прогона; null — прогон до RFC-0005"
    )
    warnings: list[str] = Field(
        default_factory=list,
        description=(
            "Предупреждения прогона, не мешающие результату: например, часть материалов "
            "не поместилась в контекст модели и была обрезана или пропущена"
        ),
    )

    @classmethod
    def of(cls, run: models.Run) -> "Run":
        execution = (run.ir or {}).get("execution", {})
        return cls(
            id=run.id,
            project_id=run.project_id,
            mode=run.mode,
            status=run.status,
            stage=run.stage,
            stage_label=stage_label(run.status, run.stage),
            progress=run.progress,
            started_at=run.started_at,
            finished_at=run.finished_at,
            summary=RunSummary.model_validate(run.summary) if run.summary else None,
            version_id=run.version_id,
            error=run.error,
            warnings=list(run.warnings),
            provider=execution.get("provider"),
            model=run.model,
            credential_id=execution.get("credential_id"),
            profile=RunProfile.of(execution.get("profile")),
        )


class RunCreate(ApiModel):
    base_version_id: UUID | None = Field(
        default=None, description="Голова, которую видит инициатор; устаревшая — 409"
    )
    replace_manual: bool = Field(
        default=False,
        description=(
            "Осознанно пересобрать из источников вместо manual; требует актуальный base_version_id"
        ),
    )

    @model_validator(mode="after")
    def explicit_replace(self) -> "RunCreate":
        if self.replace_manual and (self.mode is not RunMode.BUILD or self.base_version_id is None):
            raise ValueError("Замена ручных правок требует build и актуальный base_version_id")
        return self

    mode: RunMode = Field(description="`analyze` — только вопросы, `build` — вопросы и схема")
    credential_id: UUID | None = Field(
        default=None,
        description="Свой ключ модели; не задан — ключ по умолчанию, затем модель сервера",
    )
    model: str | None = Field(
        default=None, max_length=128, description="Модель; требует `credential_id`"
    )
    profile: RunProfile | None = Field(
        default=None, description="Профиль прогона: effort и смысловая сверка"
    )


class StageEventData(ApiModel):
    stage: RunStage
    label: str
    progress: float


class QuestionEventData(ApiModel):
    question: Question


class VersionEventData(ApiModel):
    version: Version


class DoneEventData(ApiModel):
    run: Run


class ErrorEventData(ApiModel):
    message: str


class RunStageEvent(ApiModel):
    event: Literal["stage"]
    data: StageEventData


class RunQuestionEvent(ApiModel):
    event: Literal["question"]
    data: QuestionEventData


class RunSummaryEvent(ApiModel):
    event: Literal["summary"]
    data: RunSummary


class RunVersionEvent(ApiModel):
    event: Literal["version"]
    data: VersionEventData


class RunDoneEvent(ApiModel):
    event: Literal["done"]
    data: DoneEventData


class RunErrorEvent(ApiModel):
    event: Literal["error"]
    data: ErrorEventData


class RunEvent(
    RootModel[
        Annotated[
            RunStageEvent
            | RunQuestionEvent
            | RunSummaryEvent
            | RunVersionEvent
            | RunDoneEvent
            | RunErrorEvent,
            Field(discriminator="event"),
        ]
    ]
):
    """Одно SSE-сообщение: поле `event:` — тип, `data:` — JSON из `data`, `id:` — номер.

    Порядок: `stage` на каждый этап; на этапе сверки — `question` на каждый изменённый или
    новый вопрос, затем `summary`; при сборке — `version`; последним всегда `done`
    (при ошибке перед ним — `error`). Переподключение — заголовок `Last-Event-ID`.
    """
