"""Справочник возможностей моделей и профиль запуска (RFC-0005, шаги 1–3).

Пределы качества выводятся из модели, а не из одного числа в `.env`: окно контекста и
максимум ответа задают бюджет источников и `max_tokens`, уровни effort — что пользователь
может попросить. Каталог статический и датированный; у Anthropic список моделей
(Models API: `max_input_tokens`, `max_tokens`, `capabilities`) уточняет его поверх каталога.
Неизвестная модель совместимого провайдера получает осторожные значения: окно неизвестно,
поэтому бюджет — `LLM_CONTEXT_BUDGET_CHARS`, а ответ — `LLM_JSON_MAX_TOKENS`.

Модуль не знает ни о ключах, ни о HTTP: только данные и расчёты.
"""

import re
from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import date
from typing import Any, Literal
from urllib.parse import urlsplit

type Effort = Literal["low", "medium", "high", "xhigh", "max"]
EFFORT_LEVELS: tuple[Effort, ...] = ("low", "medium", "high", "xhigh", "max")
_ALL_EFFORTS: tuple[Effort, ...] = EFFORT_LEVELS
_BASIC_EFFORTS: tuple[Effort, ...] = ("low", "medium", "high")

EFFORT_LABELS: dict[str, str] = {
    "low": "быстро",
    "medium": "обычно",
    "high": "тщательно",
    "xhigh": "очень тщательно",
    "max": "максимум",
}

# Знаков на токен для русского текста. Замера `count_tokens` на эталонах `prompt-eval` пока нет,
# поэтому берём заведомо низкое значение: кириллица у токенизаторов дробится мельче латиницы,
# а заниженная оценка даёт бюджет меньше реального окна, а не переполнение. Если оценка всё же
# ошиблась, «вход длиннее окна» переводит прогон на порции (`llm/pipeline.py`).
RU_CHARS_PER_TOKEN = 2.0
# Доля окна, которую отдаём источникам: остальное — запас на неточность оценки токенов.
CONTEXT_MARGIN = 0.8
# Системный промпт, схема ответа, вопросы и анализ, которые идут рядом с источниками. Текущая
# схема учитывается отдельно при сборке контекста, черновик repair — резервом ответа (×2).
PROMPT_OVERHEAD_TOKENS = 16_000

_ANTHROPIC_PRICES_CHECKED = date(2026, 10, 6)


@dataclass(frozen=True, slots=True)
class ModelPrices:
    """Цены в долларах за 1 млн токенов на дату проверки. Запись кеша — TTL 5 минут."""

    input: float
    output: float
    cache_read: float | None
    cache_write: float | None
    checked_on: date
    note: str | None = None


@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    """Что умеет модель. `None` у окна или ответа — неизвестно: берутся настройки сервера."""

    context_tokens: int | None = None
    max_output_tokens: int | None = None
    vision: bool = False
    pdf_input: bool = False
    tools: bool = False
    effort_levels: tuple[Effort, ...] = ()
    effort_default: Effort | None = None
    accepts_temperature: bool = True
    prices: ModelPrices | None = None
    chars_per_token: float = RU_CHARS_PER_TOKEN
    # Роль в будущей оркестрации (RFC-0004): orchestrator, worker, cheap.
    tier_hint: str | None = None
    # Модель есть в каталоге или описана провайдером; иначе — осторожные умолчания.
    known: bool = False


def _claude(
    price_in: float,
    price_out: float,
    cache_read: float,
    *,
    effort_default: Effort,
    tier: str,
    note: str | None = None,
) -> ModelCapabilities:
    return ModelCapabilities(
        context_tokens=1_000_000,
        max_output_tokens=128_000,
        vision=True,
        pdf_input=True,
        tools=True,
        effort_levels=_ALL_EFFORTS,
        effort_default=effort_default,
        # API Anthropic от 2026-10-21 отклоняет temperature/top_p/top_k у всех моделей.
        accepts_temperature=False,
        prices=ModelPrices(
            input=price_in,
            output=price_out,
            cache_read=cache_read,
            cache_write=round(price_in * 1.25, 4),
            checked_on=_ANTHROPIC_PRICES_CHECKED,
            note=note,
        ),
        tier_hint=tier,
        known=True,
    )


ANTHROPIC_CATALOG: dict[str, ModelCapabilities] = {
    "claude-fable-5-1": _claude(10.0, 50.0, 0.25, effort_default="high", tier="orchestrator"),
    "claude-opus-5-5": _claude(4.0, 20.0, 0.20, effort_default="medium", tier="orchestrator"),
    "claude-opus-5": _claude(5.0, 25.0, 0.50, effort_default="high", tier="orchestrator"),
    "claude-sonnet-5-5": _claude(2.0, 10.0, 0.20, effort_default="high", tier="worker"),
    "claude-sonnet-5": _claude(2.0, 10.0, 0.20, effort_default="high", tier="worker"),
    # Effort у Haiku 5.5 поддерживается (low…max, по умолчанию medium); старые Haiku — нет.
    "claude-haiku-5-5": _claude(
        0.10,
        0.50,
        0.01,
        effort_default="medium",
        tier="cheap",
        note="Цена для промпта до 100 тыс. токенов; дальше $0,50 / $2,50",
    ),
}

# Снимки и псевдонимы модели каталога: `claude-opus-5-5-20261001`, `claude-opus-5-5@20261001`,
# `claude-opus-5-5-latest` описываются записью `claude-opus-5-5`.
_SNAPSHOT = re.compile(r"^(?P<base>.+?)(?:[-@](?:\d{8}|latest))$")


def catalog_entry(model: str) -> ModelCapabilities | None:
    """Запись каталога Anthropic по имени модели или её датированного снимка."""
    name = model.lower()
    known = ANTHROPIC_CATALOG.get(name)
    if known is None and (match := _SNAPSHOT.match(name)):
        known = ANTHROPIC_CATALOG.get(match.group("base"))
    return known


# Модели Anthropic, которым параметр effort нельзя отправлять (400 у API).
_ANTHROPIC_NO_EFFORT = ("claude-haiku-4", "claude-haiku-3", "claude-3")
# Рассуждающие модели OpenAI: только температура по умолчанию, глубина — `reasoning_effort`.
_OPENAI_REASONING = ("o1", "o3", "o4", "gpt-5")

# Уточнения из Models API провайдера. Процессный кеш по `(провайдер, модель)`, а не по ключу:
# допущение — окно и уровни модели одинаковы для всех ключей провайдера (описано в
# `generation-quality.md`). Прогон записывает рассчитанные пределы в `ir.execution.limits`,
# поэтому восстановление после рестарта от этого кеша не зависит.
_REGISTRY_SIZE = 256
_registry: OrderedDict[tuple[str, str], ModelCapabilities] = OrderedDict()


def remember(provider: str, model: str, capabilities: ModelCapabilities) -> None:
    """Запоминает описание модели от провайдера; прогоны и проверка профиля видят его же."""
    key = (provider, model)
    _registry[key] = capabilities
    _registry.move_to_end(key)
    while len(_registry) > _REGISTRY_SIZE:
        _registry.popitem(last=False)


def forget_all() -> None:
    """Сброс уточнений провайдера (тесты)."""
    _registry.clear()


DEEPSEEK_HOST = "api.deepseek.com"


def is_deepseek(base_url: str | None) -> bool:
    """Параметр `thinking` понимает только API самого DeepSeek, а не OpenRouter или vLLM."""
    try:
        return (urlsplit(base_url or "").hostname or "").lower() == DEEPSEEK_HOST
    except ValueError:
        return False


def capabilities_for(
    provider: str, model: str, *, base_url: str | None = None
) -> ModelCapabilities:
    """Возможности модели: уточнение провайдера → каталог → осторожные умолчания."""
    provider = "openai_compatible" if provider == "deepseek" else provider
    remembered = _registry.get((provider, model))
    if remembered is not None:
        return remembered
    name = model.lower()
    match provider:
        case "anthropic":
            return catalog_entry(name) or _unknown_claude(name)
        case "openai":
            return _openai(name)
        case "openai_compatible" if is_deepseek(base_url):
            # Рассуждение DeepSeek — только вкл/выкл: low выключает, medium — как настроил
            # оператор (`DEEPSEEK_THINKING_ENABLED`), high включает.
            return ModelCapabilities(effort_levels=_BASIC_EFFORTS, effort_default="medium")
        case "openai_compatible":
            return ModelCapabilities()
        case _:
            return ModelCapabilities(accepts_temperature=False)


def _unknown_claude(name: str) -> ModelCapabilities:
    """Модель Claude не из каталога: как раньше — effort low…high, кроме старых Haiku."""
    no_effort = name.startswith(_ANTHROPIC_NO_EFFORT)
    return ModelCapabilities(
        effort_levels=() if no_effort else _BASIC_EFFORTS,
        effort_default=None if no_effort else "medium",
        accepts_temperature=False,
    )


def _openai(name: str) -> ModelCapabilities:
    if name.startswith(_OPENAI_REASONING):
        return ModelCapabilities(
            effort_levels=_BASIC_EFFORTS, effort_default="medium", accepts_temperature=False
        )
    # Температуру 0 для JSON принимают классические gpt-4*; остальным её не шлём.
    return ModelCapabilities(accepts_temperature=name.startswith(("gpt-4", "chatgpt-4")))


def from_anthropic_model(item: Any) -> ModelCapabilities:
    """Описание модели из Models API Anthropic поверх каталога (поля могут отсутствовать)."""
    base = capabilities_for("anthropic", str(item.id))
    updates: dict[str, Any] = {}
    context = getattr(item, "max_input_tokens", None)
    output = getattr(item, "max_tokens", None)
    if isinstance(context, int) and context > 0:
        updates["context_tokens"] = context
    if isinstance(output, int) and output > 0:
        updates["max_output_tokens"] = output
    caps = getattr(item, "capabilities", None)
    if caps is not None:
        updates["vision"] = _supported(getattr(caps, "image_input", None), base.vision)
        updates["pdf_input"] = _supported(getattr(caps, "pdf_input", None), base.pdf_input)
        effort = getattr(caps, "effort", None)
        if effort is not None and isinstance(getattr(effort, "supported", None), bool):
            levels = (
                tuple(
                    level
                    for level in EFFORT_LEVELS
                    if _supported(getattr(effort, level, None), default=False)
                )
                if effort.supported
                else ()
            )
            updates["effort_levels"] = levels
            default = base.effort_default
            if default not in levels:
                default = "medium" if "medium" in levels else (levels[0] if levels else None)
            updates["effort_default"] = default
    if not updates:
        return base
    return replace(base, known=True, **updates)


def _supported(value: object, default: bool) -> bool:
    flag = getattr(value, "supported", None)
    return flag if isinstance(flag, bool) else default


def nearest_effort(level: str, levels: tuple[str, ...]) -> str | None:
    """Ближайший поддерживаемый уровень: при равенстве — меньший (дешевле)."""
    if not levels:
        return None
    if level in levels:
        return level
    order = {name: index for index, name in enumerate(EFFORT_LEVELS)}
    target = order.get(level, order["medium"])
    return min(levels, key=lambda name: (abs(order.get(name, 0) - target), order.get(name, 0)))


def wire_effort(
    provider: str,
    capabilities: ModelCapabilities,
    requested: str | None,
    *,
    server_default: str | None = None,
) -> str | None:
    """Уровень, который адаптер реально отправит провайдеру; `None` — не отправлять.

    Anthropic: профиль → умолчание сервера → умолчание модели. OpenAI и DeepSeek: только из
    профиля (без него — поведение провайдера и `DEEPSEEK_THINKING_ENABLED`). Уровень
    приводится к ближайшему, который модель принимает.
    """
    levels = capabilities.effort_levels
    wanted = requested
    if provider == "anthropic":
        wanted = requested or server_default or capabilities.effort_default
    return nearest_effort(wanted, levels) if wanted else None


def json_output_tokens(capabilities: ModelCapabilities, *, configured: int, explicit: bool) -> int:
    """`max_tokens` JSON-ответа: максимум модели; `LLM_JSON_MAX_TOKENS` — потолок, если задан явно.

    У модели без известного максимума остаётся `LLM_JSON_MAX_TOKENS`, как до RFC-0005.
    """
    limit = capabilities.max_output_tokens
    if limit is None:
        return configured
    return min(limit, configured) if explicit else limit


def context_budget_chars(
    capabilities: ModelCapabilities,
    *,
    fallback_chars: int,
    output_reserve_tokens: int,
    ceiling_chars: int = 0,
) -> int:
    """Бюджет источников прогона в знаках.

    (окно − 2 × ответ − накладные промпта) × знаков на токен × запас, но не меньше
    `LLM_CONTEXT_BUDGET_CHARS`; `ceiling_chars` > 0 — потолок оператора (лимиты аккаунта).
    Ответ резервируется дважды: попытка исправления графа отправляет прежний черновик обратно.
    """
    window = capabilities.context_tokens
    budget = fallback_chars
    if window is not None:
        usable = max(window - 2 * output_reserve_tokens - PROMPT_OVERHEAD_TOKENS, 0)
        budget = max(int(usable * capabilities.chars_per_token * CONTEXT_MARGIN), fallback_chars)
    if ceiling_chars > 0:
        budget = min(budget, max(ceiling_chars, fallback_chars))
    return budget


@dataclass(frozen=True, slots=True)
class RunProfile:
    """Профиль одного прогона: `None` — умолчание сервера и модели. Ключей не содержит."""

    effort: Effort | None = None
    semantic_review: bool | None = None

    def to_json(self) -> dict[str, Any]:
        return {"effort": self.effort, "semantic_review": self.semantic_review}

    @classmethod
    def from_json(cls, value: object) -> "RunProfile":
        if not isinstance(value, dict):
            return cls()
        effort = value.get("effort")
        review = value.get("semantic_review")
        return cls(
            effort=effort if effort in EFFORT_LEVELS else None,
            semantic_review=review if isinstance(review, bool) else None,
        )


class UnsupportedEffortError(ValueError):
    """Модель не поддерживает запрошенный уровень; сообщение — для пользователя."""


def checked_profile(profile: RunProfile, capabilities: ModelCapabilities, model: str) -> RunProfile:
    """Проверяет effort по возможностям модели; у модели без рассуждения поле отбрасывается."""
    if profile.effort is None:
        return profile
    levels = capabilities.effort_levels
    if not levels:
        return replace(profile, effort=None)
    if profile.effort not in levels:
        allowed = ", ".join(f"«{EFFORT_LABELS[level]}»" for level in levels)
        raise UnsupportedEffortError(
            f"Модель {model} не поддерживает уровень «{EFFORT_LABELS[profile.effort]}». "
            f"Доступно: {allowed}"
        )
    return profile
