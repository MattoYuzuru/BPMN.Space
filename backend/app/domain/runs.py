"""Этапы прогона (RFC §5.1): порядок, подписи для интерфейса, прогресс; события для SSE."""

from dataclasses import dataclass, field
from enum import StrEnum

from app.domain.models import (
    LlmCallTotals,
    Question,
    Run,
    RunMode,
    RunStage,
    RunStatus,
    RunSummary,
    Version,
)


class RunEventKind(StrEnum):
    """Типы SSE-событий прогона. `done` — всегда последнее (и после `error`)."""

    STAGE = "stage"
    QUESTION = "question"
    SUMMARY = "summary"
    VERSION = "version"
    USAGE = "usage"
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


# Подписи этапов вызовов модели: `stage` в `llm_calls` — не этап прогона, а шаг пайплайна.
CALL_STAGE_LABELS: dict[str, str] = {
    "analyze": "Сверка вопросов",
    "structure": "Сборка схемы",
    "chat": "Помощник",
}


@dataclass(frozen=True, slots=True, kw_only=True)
class StageCost:
    """Стоимость одного этапа вызовов модели."""

    stage: str
    label: str
    calls: int
    tokens_in: int
    tokens_out: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float | None


@dataclass(frozen=True, slots=True, kw_only=True)
class RunCost:
    """Потрачено на прогон: токены, кеш, деньги и разбивка по этапам.

    `complete=False` — у части вызовов не было токенов (mock) или цен (неизвестная модель),
    поэтому сумма неполная. `cost_usd=None` — ни у одного вызова не было цены.
    """

    tokens_in: int = 0
    tokens_out: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    calls: int = 0
    cost_usd: float | None = None
    complete: bool = False
    by_stage: list[StageCost] = field(default_factory=list[StageCost])

    @classmethod
    def of(cls, totals: LlmCallTotals) -> "RunCost | None":
        """Итог вызовов модели: `None`, если прогон ещё ничего не вызывал."""
        if totals.calls == 0:
            return None
        by_stage = [
            StageCost(
                stage=stage,
                label=CALL_STAGE_LABELS.get(stage, stage),
                calls=item.calls,
                tokens_in=item.tokens_in,
                tokens_out=item.tokens_out,
                cache_read_tokens=item.cache_read_tokens,
                cache_write_tokens=item.cache_write_tokens,
                cost_usd=item.cost_usd if item.priced_calls else None,
            )
            for stage, item in sorted(totals.stages.items())
        ]
        return cls(
            tokens_in=totals.tokens_in,
            tokens_out=totals.tokens_out,
            cache_read_tokens=totals.cache_read_tokens,
            cache_write_tokens=totals.cache_write_tokens,
            calls=totals.calls,
            cost_usd=totals.cost_usd if totals.priced_calls else None,
            complete=totals.complete,
            by_stage=by_stage,
        )


type RunEventPayload = StageProgress | Question | RunSummary | Version | RunCost | Run | RunError


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
