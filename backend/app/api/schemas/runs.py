"""Схемы прогонов и SSE-событий `GET /runs/{id}/events`."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, RootModel

from app.api.schemas.common import ApiModel
from app.api.schemas.questions import Question
from app.api.schemas.versions import Version
from app.domain import models
from app.domain.models import RunMode, RunStage, RunStatus
from app.domain.runs import stage_label


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

    @classmethod
    def of(cls, run: models.Run) -> "Run":
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
        )


class RunCreate(ApiModel):
    mode: RunMode = Field(description="`analyze` — только вопросы, `build` — вопросы и схема")


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
