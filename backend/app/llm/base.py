"""Интерфейс LLM-пайплайна (RFC §5.1): два шага — «анализ» и «структура».

Реализации: `pipeline.py` (сверка вопросов и GraphIR v1, XML строит код) и
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
from app.llm.capabilities import Budget

DEADLINE_MESSAGE = (
    "Прогон не уложился в отведённое время. Повторите его или уменьшите объём материалов"
)


class PipelineError(Exception):
    """Модель не справилась (после repair-кругов). Сообщение — для пользователя."""


class OutputTruncatedError(RuntimeError):
    """Провайдер явно не завершил ответ; такой JSON не является полным результатом."""


class ContextOverflowError(RuntimeError):
    """Провайдер отклонил запрос как длиннее окна модели: можно повторить порциями."""


class CachedPrefixPrompt(str):
    """Текст запроса со стабильным началом, которое повторяется между вызовами.

    Для всех адаптеров это обычная строка `prefix + rest` (у OpenAI-совместимых провайдеров
    кеш префикса автоматический). Anthropic кеширует только по явным границам блоков,
    поэтому его адаптер отправляет `prefix` отдельным блоком с `cache_control`: повторы
    сборки графа и порции сверки не оплачивают одни и те же источники и граф заново.
    """

    prefix: str

    def __new__(cls, prefix: str, rest: str) -> "CachedPrefixPrompt":
        value = super().__new__(cls, prefix + rest)
        value.prefix = prefix
        return value


class BudgetReachedError(Exception):
    """Мягкая остановка прогона: достигнут бюджет токенов или денег (RFC-0005, шаг 5).

    Это не сбой модели: прогон переходит в `waiting` с блокирующим техническим вопросом, а
    после решения пользователя продолжается. Наследуется не от `RuntimeError`, чтобы не быть
    преобразованным в общую ошибку пайплайна.
    """

    def __init__(self, message: str, *, budget: Budget | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.budget = budget


CONTEXT_OVERFLOW_MESSAGE = "Запрос не поместился в окно модели"
_OVERFLOW_MARKERS = (
    "prompt is too long",
    "input is too long",
    "context length",
    "context_length_exceeded",
    "maximum context",
    "context window",
    "too many tokens",
)


def is_context_overflow(status: int, text: str) -> bool:
    """HTTP 413 или 400 с признаком «вход длиннее окна» в тексте ошибки провайдера."""
    if status == 413:  # noqa: PLR2004 — Request Entity Too Large
        return True
    lowered = text.lower()
    return status == 400 and any(marker in lowered for marker in _OVERFLOW_MARKERS)  # noqa: PLR2004


class ProcessPipeline(Protocol):
    @property
    def provider(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    async def aclose(self) -> None:
        """Освободить соединения клиента провайдера."""
        ...

    async def analyze(self, context: RunContext) -> AnalysisResult:
        """Участники, шаги, условия → обновления прежних вопросов и новые вопросы."""
        ...

    async def structure(self, context: RunContext, analysis: AnalysisResult) -> DiagramDraft:
        """Схема процесса с координатами и трассировкой «элемент → цитата»."""
        ...


@dataclass(slots=True)
class LlmUsage:
    """Токены провайдера, накопленные за шаг пайплайна (все его запросы к модели).

    `tokens_in` — все входные токены, включая чтение и запись кеша: так их считает провайдер.
    `cache_read_tokens` и `cache_write_tokens` — части `tokens_in`, оплачиваемые по своим ценам
    ([RFC-0005](../../../docs/rfc/0005-full-model-capacity-and-cost.md)); без них стоимость
    завышалась бы по цене обычного входа.
    """

    tokens_in: int = 0
    tokens_out: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    requests: int = 0

    @property
    def uncached_in(self) -> int:
        """Входные токены, оплачиваемые по обычной цене входа."""
        return max(self.tokens_in - self.cache_read_tokens - self.cache_write_tokens, 0)

    def add(self, other: "LlmUsage") -> None:
        self.tokens_in += other.tokens_in
        self.tokens_out += other.tokens_out
        self.cache_read_tokens += other.cache_read_tokens
        self.cache_write_tokens += other.cache_write_tokens
        self.requests += other.requests


_usage: ContextVar[LlmUsage | None] = ContextVar("llm_usage", default=None)
# Накопитель за весь прогон (не сбрасывается на каждом шаге): нужен бюджету и итогу стоимости.
_totals: ContextVar[LlmUsage | None] = ContextVar("llm_usage_totals", default=None)
_deadline: ContextVar[float | None] = ContextVar("llm_deadline", default=None)
_budget: ContextVar[Budget | None] = ContextVar("llm_budget", default=None)


@contextmanager
def track_usage() -> Iterator[LlmUsage]:
    """Собирает токены всех запросов к модели внутри блока."""
    usage = LlmUsage()
    token = _usage.set(usage)
    try:
        yield usage
    finally:
        _usage.reset(token)


@contextmanager
def track_run_usage(initial: LlmUsage | None = None) -> Iterator[LlmUsage]:
    """Накопитель токенов за весь прогон: шаги пишут в него через `record_usage`.

    `initial` — уже потраченное до этого исполнения (продолжение прогона после `waiting`):
    бюджет считается по всему прогону, а не только по последней попытке.
    """
    totals = LlmUsage()
    if initial is not None:
        totals.add(initial)
    token = _totals.set(totals)
    try:
        yield totals
    finally:
        _totals.reset(token)


def usage_totals() -> LlmUsage | None:
    """Токены, накопленные за прогон; `None` — вне `track_run_usage`."""
    return _totals.get()


def record_usage(
    *,
    tokens_in: int | None,
    tokens_out: int | None,
    cache_read: int | None = None,
    cache_write: int | None = None,
) -> None:
    """Вызывает адаптер после ответа провайдера; вне `track_usage` ничего не делает."""
    read = cache_read or 0
    write = cache_write or 0
    for usage in (_usage.get(), _totals.get()):
        if usage is None:
            continue
        usage.requests += 1
        usage.tokens_in += tokens_in or 0
        usage.tokens_out += tokens_out or 0
        usage.cache_read_tokens += read
        usage.cache_write_tokens += write


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


@contextmanager
def run_budget(budget: Budget | None) -> Iterator[None]:
    """Бюджет прогона: пайплайн проверяет его перед каждым запросом к модели."""
    token = _budget.set(budget)
    try:
        yield
    finally:
        _budget.reset(token)


def current_budget() -> Budget | None:
    """Бюджет текущего прогона; `None` — без бюджета (или вне прогона)."""
    return _budget.get()
