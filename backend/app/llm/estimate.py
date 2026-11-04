"""Оценка стоимости и объёма прогона до запуска (RFC-0005, шаг 4).

Чистый модуль: не знает ни о БД, ни о HTTP, ни о ключах. Повторяет текущие правила пайплайна
(`llm/question_analysis.py`, `llm/evidence_context.py`, `llm/graph_generation.py`) в виде
плана вызовов: сколько запросов будет у каждого этапа, сколько токенов они прочитают и вернут.
Ответ — диапазон, а не одно число: точное число запросов зависит от материалов и решений
модели. Границы диапазона заведомо осторожные:

- минимум — проект целиком помещается в бюджет, исправления не понадобились, ответы короткие;
- максимум — материалов хватает только на порции, каждый этап использовал все попытки
  исправления, а ответ доходил до своего лимита.

Цены берутся из датированного справочника возможностей (`capabilities.prices`). Если цены
модели неизвестны (совместимый провайдер, mock), стоимость не рассчитывается, а `complete=False`:
интерфейс обязан показать «оценка неполная», а не ноль.

Стоимость входа считается по цене чтения кеша в минимуме и записи кеша в максимуме: провайдер
кеширует повторяющийся префикс (системный промпт и схему), и реальный счёт лежит между этими
границами. У модели без цен кеша используется обычная цена входа.
"""

import math
from dataclasses import dataclass, field
from datetime import date

from app.domain.models import RunMode
from app.llm.base import LlmUsage
from app.llm.capabilities import ModelCapabilities, ModelPrices

CURRENCY = "USD"

# Накладные токены одного запроса: системный промпт, схема ответа и инструкции.
PROMPT_OVERHEAD_TOKENS = 8_000
# Накладные токены запроса порции: тот же системный промпт, но короче схема.
CHUNK_OVERHEAD_TOKENS = 2_000
# Доля входа, которую модель возвращает ответом: границы для диапазона ответа.
OUTPUT_MIN_RATIO = 0.10
OUTPUT_MAX_RATIO = 0.50
# Минимальный и «двухминимальный» ответ: совсем короткий ответ на этап нереалистичен.
OUTPUT_FLOOR_TOKENS = 1_024
# Сколько исправлений допускает цикл repair (`graph_generation.py`, `question_analysis.py`).
REPAIR_ATTEMPTS = 3
# Во сколько раз уровень effort увеличивает объём рассуждения и ответа.
EFFORT_OUTPUT_FACTOR: dict[str, float] = {
    "low": 0.6,
    "medium": 1.0,
    "high": 1.5,
    "xhigh": 2.0,
    "max": 2.5,
}
# Длительность: запрос + генерация ответа + чтение входа. Оценка для интерфейса, не SLA.
CALL_BASE_SEC = 6.0
OUTPUT_TOKENS_PER_SEC = 60.0
PREFILL_TOKENS_PER_SEC = 3_000.0
# Ответ проверяющего короткий: список подтверждённых ошибок, а не схема.
REVIEW_OUTPUT_TOKENS = 2_048

_ANALYSIS_STAGE = "analyze"
_STRUCTURE_STAGE = "structure"
_EVIDENCE_STAGE = "evidence"
_REVIEW_STAGE = "review"

STAGE_LABELS: dict[str, str] = {
    _ANALYSIS_STAGE: "Сверка вопросов",
    _EVIDENCE_STAGE: "Извлечение оснований",
    _STRUCTURE_STAGE: "Сборка схемы",
    _REVIEW_STAGE: "Смысловая проверка",
}


@dataclass(frozen=True, slots=True)
class IntRange:
    """Целочисленный диапазон `[min, max]`."""

    min: int
    max: int

    def __post_init__(self) -> None:
        if self.min < 0 or self.max < self.min:
            raise ValueError("Некорректный диапазон оценки")

    def scaled(self, factor: int | float) -> "IntRange":
        return IntRange(min=round(self.min * factor), max=round(self.max * factor))

    def plus(self, other: "IntRange") -> "IntRange":
        return IntRange(min=self.min + other.min, max=self.max + other.max)


@dataclass(frozen=True, slots=True)
class CostRange:
    """Стоимость в долларах; `None` — цены модели неизвестны."""

    min_usd: float | None
    max_usd: float | None
    currency: str = CURRENCY


@dataclass(frozen=True, slots=True)
class StageEstimate:
    """План одного этапа: сколько запросов, токенов и денег он потребует."""

    stage: str
    label: str
    calls: IntRange
    tokens_in: IntRange
    tokens_out: IntRange
    cost: CostRange | None


@dataclass(frozen=True, slots=True)
class EstimateInput:
    """Всё, что нужно планировщику; собирается сервисом оценки из проекта и модели."""

    mode: RunMode
    source_chars: int
    budget_chars: int
    chunk_chars: int
    current_xml_chars: int = 0
    questions: int = 0
    semantic_review: bool = False
    json_max_tokens: int = 16_384
    chunk_max_tokens: int = 16_384
    capabilities: ModelCapabilities = field(default_factory=ModelCapabilities)
    effort: str | None = None
    # Калибровка `count_tokens` по образцу текста; `None` — значение справочника.
    chars_per_token: float | None = None
    # Агентный режим RFC-0004: один этап «агентные ходы» вместо этапов конвейера.
    agent_mode: bool = False
    agent_max_steps: int = 24


@dataclass(frozen=True, slots=True)
class RunEstimate:
    """Оценка одного прогона: диапазоны токенов, денег и времени, разбивка по этапам."""

    tokens: IntRange
    calls: IntRange
    cost: CostRange | None
    duration_sec: IntRange
    breakdown: list[StageEstimate]
    complete: bool
    priced_on: date | None
    notes: list[str]
    # Для интерфейса: на какой модели и у какого провайдера считалась оценка.
    model: str | None = None
    provider: str | None = None


@dataclass(frozen=True, slots=True)
class UsageCost:
    """Стоимость уже состоявшихся вызовов модели по ценам на момент вызова."""

    cost_usd: float | None
    complete: bool
    checked_on: date | None


def cost_of_usage(usage: LlmUsage | None, prices: ModelPrices | None) -> UsageCost:
    """Стоимость накопленных токенов; `complete=False`, если часть цены неизвестна.

    `usage.tokens_in` включает чтение и запись кеша, поэтому обычный вход считается как
    `uncached_in`. Без цены кеша соответствующая часть оценивается по цене обычного входа —
    стоимость не занижается, но помечается неполной.
    """
    checked_on = prices.checked_on if prices is not None else None
    if usage is None or usage.requests == 0:
        return UsageCost(cost_usd=None, complete=prices is not None, checked_on=checked_on)
    if prices is None:
        return UsageCost(cost_usd=None, complete=False, checked_on=None)
    read_price = prices.cache_read if prices.cache_read is not None else prices.input
    write_price = prices.cache_write if prices.cache_write is not None else prices.input
    complete = (usage.cache_read_tokens == 0 or prices.cache_read is not None) and (
        usage.cache_write_tokens == 0 or prices.cache_write is not None
    )
    total = (
        usage.uncached_in * prices.input
        + usage.cache_read_tokens * read_price
        + usage.cache_write_tokens * write_price
        + usage.tokens_out * prices.output
    ) / 1_000_000
    return UsageCost(cost_usd=round(total, 6), complete=complete, checked_on=checked_on)


def estimate_run(inputs: EstimateInput) -> RunEstimate:
    """План вызовов и оценка стоимости по текущим правилам конвейера."""
    capabilities = inputs.capabilities
    prices = capabilities.prices
    chars_per_token = _chars_per_token(inputs)
    overhead = PROMPT_OVERHEAD_TOKENS + math.ceil(inputs.current_xml_chars / chars_per_token)
    total_tokens = math.ceil(inputs.source_chars / chars_per_token)
    budget_chars = max(inputs.budget_chars, 1)
    fits = inputs.source_chars <= budget_chars
    chunk_count = max(math.ceil(inputs.source_chars / max(inputs.chunk_chars, 1)), 1)
    effort = inputs.effort or "medium"
    effort_factor = EFFORT_OUTPUT_FACTOR.get(effort, 1.0)

    stages: list[StageEstimate] = []
    if inputs.agent_mode:
        # Диапазон агентного прогона: от «прочитал оглавление и сдал» до лимита ходов.
        stages.append(
            _agent_stage(
                inputs,
                overhead=overhead,
                total_tokens=total_tokens,
                effort_factor=effort_factor,
                chars_per_token=chars_per_token,
                prices=prices,
            )
        )
    else:
        stages.append(
            _analysis_stage(
                inputs,
                total_tokens=total_tokens,
                overhead=overhead,
                fits=fits,
                chunk_count=chunk_count,
                effort_factor=effort_factor,
                chars_per_token=chars_per_token,
                prices=prices,
            )
        )
    if not inputs.agent_mode and inputs.mode is RunMode.BUILD:
        if not fits:
            stages.append(
                _evidence_stage(
                    inputs,
                    chunk_count=chunk_count,
                    effort_factor=effort_factor,
                    chars_per_token=chars_per_token,
                    prices=prices,
                )
            )
        stages.append(
            _structure_stage(
                inputs,
                total_tokens=total_tokens,
                overhead=overhead,
                fits=fits,
                effort_factor=effort_factor,
                chars_per_token=chars_per_token,
                prices=prices,
            )
        )
        if inputs.semantic_review:
            stages.append(
                _review_stage(
                    inputs,
                    chunk_count=chunk_count,
                    chars_per_token=chars_per_token,
                    prices=prices,
                )
            )

    tokens = IntRange(min=0, max=0)
    calls = IntRange(min=0, max=0)
    duration_min = 0.0
    duration_max = 0.0
    cost_min = 0.0
    cost_max = 0.0
    for stage in stages:
        tokens = tokens.plus(
            IntRange(
                min=stage.tokens_in.min + stage.tokens_out.min,
                max=stage.tokens_in.max + stage.tokens_out.max,
            )
        )
        calls = calls.plus(stage.calls)
        duration_min += _duration(stage.calls.min, stage.tokens_in.min, stage.tokens_out.min)
        duration_max += _duration(stage.calls.max, stage.tokens_in.max, stage.tokens_out.max)
        if stage.cost is not None:
            cost_min += stage.cost.min_usd or 0.0
            cost_max += stage.cost.max_usd or 0.0

    notes = [
        "Оценка приблизительная: число запросов и длина ответов зависят от материалов и модели"
    ]
    if inputs.agent_mode:
        notes.append(
            "Агентный режим: число ходов и объём чтения выбирает модель; верхняя граница — "
            "лимит ходов и бюджет прогона"
        )
    if inputs.questions:
        notes.append(f"Вопросов в проекте: {inputs.questions}; ответы и допущения идут в контекст")
    cost: CostRange | None = None
    if prices is not None:
        cost = CostRange(min_usd=round(cost_min, 4), max_usd=round(cost_max, 4))
    else:
        notes.append(
            "Цены модели неизвестны: стоимость не рассчитана. Оценка неполная (complete=false)"
        )
    return RunEstimate(
        tokens=tokens,
        calls=calls,
        cost=cost,
        duration_sec=IntRange(min=round(duration_min), max=round(duration_max)),
        breakdown=stages,
        complete=prices is not None,
        priced_on=prices.checked_on if prices is not None else None,
        notes=notes,
    )


def _chars_per_token(inputs: EstimateInput) -> float:
    """Знаков на токен: калибровка `count_tokens` главнее справочника, но не меньше 0,5."""
    value = inputs.chars_per_token or inputs.capabilities.chars_per_token
    if value is None or value <= 0:
        return 2.0
    return max(value, 0.5)


def _output_range(
    per_call_in: IntRange,
    calls: IntRange,
    *,
    cap: int,
    effort_factor: float,
    short: bool = False,
) -> IntRange:
    """Суммарный ответ этапа: на каждый запрос действует свой лимит `max_tokens`.

    Лимит одного ответа — `cap`; запросов могло быть до `calls.max`, и каждый мог упереться
    в свой предел. Поэтому верхняя граница этапа — `cap × calls.max`, а не `cap` на весь этап.
    """
    cap = max(cap, 1)
    if short:
        per_min = min(REVIEW_OUTPUT_TOKENS, cap)
        per_max = min(REVIEW_OUTPUT_TOKENS * 2, cap)
    else:
        per_min = min(
            max(round(per_call_in.min * OUTPUT_MIN_RATIO * effort_factor), OUTPUT_FLOOR_TOKENS),
            cap,
        )
        per_max = cap
    lower = per_min * calls.min
    upper = max(per_max, per_min) * calls.max
    return IntRange(min=lower, max=max(lower, upper))


def _stage_tokens(per_call_in: IntRange, calls: IntRange) -> IntRange:
    """Суммарные входные токены этапа: число запросов учитывается и в минимуме, и в максимуме."""
    return IntRange(
        min=per_call_in.min * calls.min,
        max=per_call_in.max * calls.max,
    )


def _stage(
    *,
    stage: str,
    per_call_in: IntRange,
    calls: IntRange,
    cap: int,
    effort_factor: float,
    prices: ModelPrices | None,
    short: bool = False,
) -> StageEstimate:
    """Собирает этап: вход, ответ и стоимость с учётом числа запросов."""
    tokens_in = _stage_tokens(per_call_in, calls)
    tokens_out = _output_range(
        per_call_in, calls, cap=cap, effort_factor=effort_factor, short=short
    )
    return StageEstimate(
        stage=stage,
        label=STAGE_LABELS[stage],
        calls=calls,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost=_stage_cost(prices, tokens_in=tokens_in, tokens_out=tokens_out),
    )


def _stage_cost(
    prices: ModelPrices | None,
    *,
    tokens_in: IntRange,
    tokens_out: IntRange,
) -> CostRange | None:
    """Стоимость этапа: вход по цене кеша (min — чтение, max — запись), выход по цене ответа."""
    if prices is None:
        return None
    read_price = prices.cache_read if prices.cache_read is not None else prices.input
    write_price = prices.cache_write if prices.cache_write is not None else prices.input
    min_usd = (tokens_in.min * read_price + tokens_out.min * prices.output) / 1_000_000
    max_usd = (tokens_in.max * write_price + tokens_out.max * prices.output) / 1_000_000
    return CostRange(min_usd=round(min_usd, 4), max_usd=round(max_usd, 4))


def _duration(calls: int, tokens_in: int, tokens_out: int) -> float:
    """Секунды этапа: накладные на запрос, чтение входа и генерация ответа.

    `tokens_in`/`tokens_out` — суммы по всем запросам этапа, поэтому делить их на `calls`
    повторно не нужно: время чтения и генерации уже распределено по запросам.
    """
    if calls <= 0:
        return 0.0
    return (
        calls * CALL_BASE_SEC
        + tokens_in / PREFILL_TOKENS_PER_SEC
        + tokens_out / OUTPUT_TOKENS_PER_SEC
    )


def _agent_stage(
    inputs: EstimateInput,
    *,
    overhead: int,
    total_tokens: int,
    effort_factor: float,
    chars_per_token: float,
    prices: ModelPrices | None,
) -> StageEstimate:
    """Агентные ходы (RFC-0004): от «оглавление и submit» до исчерпания лимита ходов.

    Точное число ходов решает модель. Нижняя граница — два хода (оглавление и submit),
    верхняя — `agent_max_steps`; вход одного хода ограничен бюджетом источников, выход —
    максимумом ответа модели. Оценка честно помечается приблизительной в `notes`.
    """
    steps = max(inputs.agent_max_steps, 2)
    calls = IntRange(min=2, max=steps)
    index_tokens = math.ceil(2_000 / chars_per_token)
    per_call_in = IntRange(
        min=overhead + index_tokens,
        max=overhead + max(min(total_tokens, inputs.budget_chars // 2), index_tokens),
    )
    # Выход этапа уже учитывает число ходов (cap × calls.max), вход — ниже через `_stage_tokens`.
    tokens_out = _output_range(
        per_call_in, calls, cap=inputs.json_max_tokens, effort_factor=effort_factor, short=True
    )
    tokens_in = _stage_tokens(per_call_in, calls)
    return StageEstimate(
        stage="agent",
        label="Агентные ходы",
        calls=calls,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost=_stage_cost(prices, tokens_in=tokens_in, tokens_out=tokens_out),
    )


def _analysis_stage(
    inputs: EstimateInput,
    *,
    total_tokens: int,
    overhead: int,
    fits: bool,
    chunk_count: int,
    effort_factor: float,
    chars_per_token: float,
    prices: ModelPrices | None,
) -> StageEstimate:
    """Сверка вопросов: один запрос по всему проекту или порции с исправлениями."""
    chunk_tokens = math.ceil(inputs.chunk_chars / chars_per_token)
    if fits:
        per_call = IntRange(min=total_tokens + overhead, max=total_tokens + overhead)
        calls = IntRange(min=1, max=1 + REPAIR_ATTEMPTS)
        cap = inputs.json_max_tokens
    else:
        per_call = IntRange(
            min=chunk_tokens + CHUNK_OVERHEAD_TOKENS,
            max=chunk_tokens + CHUNK_OVERHEAD_TOKENS + overhead,
        )
        calls = IntRange(min=chunk_count, max=chunk_count + REPAIR_ATTEMPTS)
        cap = inputs.chunk_max_tokens
    return _stage(
        stage=_ANALYSIS_STAGE,
        per_call_in=per_call,
        calls=calls,
        cap=cap,
        effort_factor=effort_factor,
        prices=prices,
    )


def _evidence_stage(
    inputs: EstimateInput,
    *,
    chunk_count: int,
    effort_factor: float,
    chars_per_token: float,
    prices: ModelPrices | None,
) -> StageEstimate:
    """Извлечение оснований порциями (только когда проект не помещается в бюджет)."""
    per_call = math.ceil(inputs.chunk_chars / chars_per_token) + CHUNK_OVERHEAD_TOKENS
    return _stage(
        stage=_EVIDENCE_STAGE,
        per_call_in=IntRange(min=per_call, max=per_call),
        calls=IntRange(min=chunk_count, max=chunk_count),
        cap=inputs.chunk_max_tokens,
        effort_factor=effort_factor,
        prices=prices,
        short=True,
    )


def _structure_stage(
    inputs: EstimateInput,
    *,
    total_tokens: int,
    overhead: int,
    fits: bool,
    effort_factor: float,
    chars_per_token: float,
    prices: ModelPrices | None,
) -> StageEstimate:
    """Сборка графа: основания сжимаются до бюджета, затем repair-цикл."""
    budget_tokens = max(math.ceil(inputs.budget_chars / chars_per_token), 1)
    evidence_tokens = total_tokens if fits else min(total_tokens, budget_tokens)
    per_call = evidence_tokens + overhead
    return _stage(
        stage=_STRUCTURE_STAGE,
        per_call_in=IntRange(min=per_call, max=per_call),
        calls=IntRange(min=1, max=1 + REPAIR_ATTEMPTS),
        cap=inputs.json_max_tokens,
        effort_factor=effort_factor,
        prices=prices,
    )


def _review_stage(
    inputs: EstimateInput,
    *,
    chunk_count: int,
    chars_per_token: float,
    prices: ModelPrices | None,
) -> StageEstimate:
    """Независимая смысловая сверка читает полный снимок порциями."""
    per_call = math.ceil(inputs.chunk_chars / chars_per_token) + CHUNK_OVERHEAD_TOKENS
    return _stage(
        stage=_REVIEW_STAGE,
        per_call_in=IntRange(min=per_call, max=per_call),
        calls=IntRange(min=chunk_count, max=chunk_count + REPAIR_ATTEMPTS),
        cap=inputs.chunk_max_tokens,
        effort_factor=1.0,
        prices=prices,
        short=True,
    )
