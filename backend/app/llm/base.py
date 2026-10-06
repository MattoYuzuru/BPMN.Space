"""Интерфейс LLM-пайплайна (RFC §5.1): два шага — «анализ» и «структура».

Реализации: `openai_compatible.py` (сверка вопросов и GraphIR v1, XML строит код) и
`mock.py` (записанные ответы из `app/fixtures/playbook.py`). Граф, ограниченный repair-цикл
и поддерживаемый поднабор описаны в `docs/backend/generation-quality.md`.

Модуль также хранит то, что разделяют сервис прогонов и адаптеры, не меняя сигнатуры шагов:
срок прогона и счётчик токенов живут в `ContextVar`, поэтому видны и в потоке `to_thread`.
"""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Protocol

from app.domain.analysis import AnalysisResult, DiagramDraft, RunContext

DEADLINE_MESSAGE = (
    "Прогон не уложился в отведённое время. Повторите его или уменьшите объём материалов"
)


class PipelineError(Exception):
    """Модель не справилась (после repair-кругов). Сообщение — для пользователя."""


class ProcessPipeline(Protocol):
    @property
    def model_name(self) -> str: ...

    async def analyze(self, context: RunContext) -> AnalysisResult:
        """Участники, шаги, условия → обновления прежних вопросов и новые вопросы."""
        ...

    async def structure(self, context: RunContext, analysis: AnalysisResult) -> DiagramDraft:
        """Схема процесса с координатами и трассировкой «элемент → цитата»."""
        ...


@dataclass(slots=True)
class LlmUsage:
    """Токены провайдера, накопленные за один шаг пайплайна (все его запросы к модели)."""

    tokens_in: int = 0
    tokens_out: int = 0
    requests: int = 0


_usage: ContextVar[LlmUsage | None] = ContextVar("llm_usage", default=None)
_deadline: ContextVar[float | None] = ContextVar("llm_deadline", default=None)


@contextmanager
def track_usage() -> Iterator[LlmUsage]:
    """Собирает токены всех запросов к модели внутри блока."""
    usage = LlmUsage()
    token = _usage.set(usage)
    try:
        yield usage
    finally:
        _usage.reset(token)


def record_usage(*, tokens_in: int | None, tokens_out: int | None) -> None:
    """Вызывает адаптер после ответа провайдера; вне `track_usage` ничего не делает."""
    usage = _usage.get()
    if usage is None:
        return
    usage.requests += 1
    usage.tokens_in += tokens_in or 0
    usage.tokens_out += tokens_out or 0


@contextmanager
def run_deadline(seconds: float | None) -> Iterator[None]:
    """Срок прогона: новые запросы к модели после него не начинаются."""
    token = _deadline.set(time.monotonic() + seconds if seconds else None)
    try:
        yield
    finally:
        _deadline.reset(token)


def remaining_sec() -> float | None:
    """Сколько секунд осталось до срока прогона; `None` — срока нет."""
    deadline = _deadline.get()
    return None if deadline is None else deadline - time.monotonic()
