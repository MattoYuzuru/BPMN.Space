"""Этапы прогона (RFC §5.1): порядок, подписи для интерфейса, прогресс; события для SSE."""

from dataclasses import dataclass
from enum import StrEnum

from app.domain.models import Question, Run, RunMode, RunStage, RunStatus, RunSummary, Version


class RunEventKind(StrEnum):
    """Типы SSE-событий прогона. `done` — всегда последнее (и после `error`)."""

    STAGE = "stage"
    QUESTION = "question"
    SUMMARY = "summary"
    VERSION = "version"
    DONE = "done"
    ERROR = "error"


@dataclass(frozen=True, slots=True, kw_only=True)
class StageProgress:
    stage: RunStage
    label: str
    progress: float


@dataclass(frozen=True, slots=True, kw_only=True)
class RunError:
    message: str


type RunEventPayload = StageProgress | Question | RunSummary | Version | Run | RunError


@dataclass(frozen=True, slots=True, kw_only=True)
class RunEvent:
    """Событие прогона: `id` — порядковый номер внутри прогона (для `Last-Event-ID`)."""

    id: int
    kind: RunEventKind
    payload: RunEventPayload


STAGE_LABELS: dict[RunStage, str] = {
    RunStage.READING_SOURCES: "Читаю источники",
    RunStage.EXTRACTING: "Ищу участников и шаги",
    RunStage.RECONCILING: "Сверяю вопросы",
    RunStage.STRUCTURING: "Строю структуру процесса",
    RunStage.VALIDATING: "Проверяю схему",
    RunStage.LAYOUT: "Раскладываю схему",
}

QUEUED_LABEL = "В очереди"
SUCCEEDED_LABEL = "Готово"
FAILED_LABEL = "Ошибка"
CANCELLED_LABEL = "Остановлено"

_ANALYZE_STAGES = (RunStage.READING_SOURCES, RunStage.EXTRACTING, RunStage.RECONCILING)
_BUILD_STAGES = (
    *_ANALYZE_STAGES,
    RunStage.STRUCTURING,
    RunStage.VALIDATING,
    RunStage.LAYOUT,
)

ACTIVE_STATUSES = frozenset({RunStatus.QUEUED, RunStatus.RUNNING})


def stages_for(mode: RunMode) -> tuple[RunStage, ...]:
    """Анализ — только сверка вопросов; сборка — анализ плюс структура, проверка и раскладка."""
    return _BUILD_STAGES if mode is RunMode.BUILD else _ANALYZE_STAGES


def progress_at(mode: RunMode, stage: RunStage) -> float:
    """Доля выполненной работы в момент начала этапа: 0 для первого, меньше 1 для последнего."""
    stages = stages_for(mode)
    return round(stages.index(stage) / len(stages), 3)


def stage_label(status: RunStatus, stage: RunStage | None) -> str:
    if status is RunStatus.SUCCEEDED:
        return SUCCEEDED_LABEL
    if status is RunStatus.FAILED:
        return FAILED_LABEL
    if status is RunStatus.CANCELLED:
        return CANCELLED_LABEL
    if status is RunStatus.QUEUED or stage is None:
        return QUEUED_LABEL
    return STAGE_LABELS[stage]
