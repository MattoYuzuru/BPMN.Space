"""Каталог провайдеров для настроек «Инструменты» (RFC-0006, шаг 6).

Что показывает: какие задачи закрывают инструменты (`Capability`), какие провайдеры это умеют,
где взять ключ, что даёт бесплатный уровень, есть ли размещение данных в РФ и что закрывает
ключ модели без отдельного ключа. Данные проверены по страницам провайдеров **04.11.2026**
([tool-providers-2026-11.md](../../../docs/research/tool-providers-2026-11.md)); цены и
бесплатные уровни меняются, поэтому дата проверки — часть ответа API.

Это не дубль `GET /me/credentials`: карточки там отвечают «что у меня уже подключено», а каталог
— «чем это можно закрыть и куда идти за ключом». Признак `supported` берётся из
`AdapterRegistry.implements` (LLM — из `USER_PROVIDERS`): у контрактов провайдеров (Mistral OCR,
Yandex Vision) ключ можно сохранить, но вызовов ещё нет, поэтому каталог показывает их как
неподдержанные, и интерфейс не предлагает их как рабочие.
"""

from dataclasses import dataclass, replace
from datetime import date

from app.domain.capabilities import (
    CAPABILITY_DESCRIPTIONS,
    CAPABILITY_LABELS,
    CAPABILITY_TOOLS,
    Capability,
    CredentialKind,
    kinds_for_capability,
)
from app.ingest.adapters import AdapterRegistry
from app.llm.client import USER_PROVIDERS

# Дата сверки данных каталога: показывается в интерфейсе рядом с «где взять ключ».
CATALOG_CHECKED_ON = date(2026, 11, 4)


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogProvider:
    """Провайдер одной возможности: подпись, страница ключа и что он даёт."""

    id: str
    label: str
    key_url: str | None = None
    free_tier: str | None = None
    notes: str | None = None
    rf: bool = False
    model_covers: bool = False
    supported: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogCapability:
    """Карточка возможности: подписи из справочника домена, провайдеры и покрытие моделью."""

    capability: Capability
    providers: tuple[CatalogProvider, ...] = ()
    model_coverage: str | None = None

    @property
    def label(self) -> str:
        return CAPABILITY_LABELS[self.capability]

    @property
    def description(self) -> str:
        return CAPABILITY_DESCRIPTIONS[self.capability]

    @property
    def tool(self) -> str:
        """Имя инструмента, которое увидит модель (RFC-0006)."""
        return CAPABILITY_TOOLS[self.capability]

    @property
    def kinds(self) -> tuple[CredentialKind, ...]:
        return kinds_for_capability(self.capability)


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolCatalog:
    """Каталог целиком: дата проверки и карточки всех возможностей."""

    checked_on: date
    capabilities: tuple[CatalogCapability, ...]


_FREE_TAVILY = "1000 кредитов/мес без карты"
_FREE_BRAVE = "$5 кредитов/мес, карта обязательна"
_FREE_EXA = "$20 стартовых кредитов и $10/мес"
_FREE_JINA = "20 запросов/мин без ключа; 500/мин и 10 млн токенов с ключом"
_FREE_FIRECRAWL = "1000 кредитов/мес без карты"

_ANTHROPIC_KEY_URL = "https://platform.claude.com/settings/keys"
_OPENAI_KEY_URL = "https://platform.openai.com/settings/organization/api-keys"
_YANDEX_KEY_URL = "https://yandex.cloud/ru/docs/iam/concepts/authorization/api-key"

# Провайдеры по возможностям: порядок — как в таблицах каталога research от 04.11.2026.
_PROVIDERS: dict[Capability, tuple[CatalogProvider, ...]] = {
    Capability.LLM: (
        CatalogProvider(
            id="anthropic",
            label="Anthropic (Claude)",
            key_url=_ANTHROPIC_KEY_URL,
            notes=(
                "РФ не поддержана. Окно до 1M, серверные поиск и чтение страниц — оплата за вызов"
            ),
            supported=True,
        ),
        CatalogProvider(
            id="openai",
            label="OpenAI",
            key_url=_OPENAI_KEY_URL,
            notes="РФ не поддержана; тот же ключ закрывает распознавание речи и изображения",
            supported=True,
        ),
        CatalogProvider(
            id="openai_compatible",
            label="Совместимый с OpenAI сервер",
            notes="vLLM, OpenRouter, DeepSeek: ключ и адрес API выдаёт выбранный сервер",
            supported=True,
        ),
        CatalogProvider(
            id="deepseek",
            label="DeepSeek",
            key_url="https://platform.deepseek.com/api_keys",
            notes="Работает из РФ; подключается как совместимый с OpenAI",
            supported=False,
        ),
        CatalogProvider(
            id="openrouter",
            label="OpenRouter",
            key_url="https://openrouter.ai/settings/keys",
            notes="Совместимый API: модели многих провайдеров одним ключом",
            supported=False,
        ),
        CatalogProvider(
            id="yandex",
            label="Yandex Cloud (YandexGPT)",
            key_url=_YANDEX_KEY_URL,
            notes=(
                "Размещение в РФ. Нужен сервисный аккаунт → API-ключ (не IAM-токен); "
                "грант от 4000 ₽ на 60 дней"
            ),
            rf=True,
            supported=False,
        ),
    ),
    Capability.SPEECH_TO_TEXT: (
        CatalogProvider(
            id="deepgram",
            label="Deepgram",
            key_url="https://console.deepgram.com",
            free_tier="$200 стартовых без карты",
            notes="Nova-3 $0,0077/мин, говорящие +$0,002/мин; файл до 2 ГБ",
            supported=True,
        ),
        CatalogProvider(
            id="openai",
            label="OpenAI (transcribe)",
            key_url=_OPENAI_KEY_URL,
            notes=("Тот же ключ, что модели; РФ не поддержана; говорящие зависят от модели"),
            supported=True,
        ),
        CatalogProvider(
            id="groq",
            label="Groq (Whisper)",
            key_url="https://console.groq.com/keys",
            free_tier="20 запросов/мин и 2000 запросов в день",
            notes="Whisper turbo $0,04/ч; файл до 100 МБ; говорящих нет",
            supported=True,
        ),
        CatalogProvider(
            id="openai_compatible",
            label="Совместимый с OpenAI сервер",
            notes="Нужен /audio/transcriptions; адрес и ключ выдаёт ваш сервер",
            supported=True,
        ),
        CatalogProvider(
            id="elevenlabs",
            label="ElevenLabs (Scribe)",
            key_url="https://elevenlabs.io/app/settings/api-keys",
            notes="Scribe v2 $0,22/ч; тот же ключ даёт синтез речи",
            supported=False,
        ),
        CatalogProvider(
            id="assemblyai",
            label="AssemblyAI",
            key_url="https://www.assemblyai.com/dashboard",
            free_tier="$50 без карты",
            notes="Universal-2 $0,15/ч, русский есть; принимает только по URL, не файлом",
            supported=False,
        ),
        CatalogProvider(
            id="yandex",
            label="Yandex SpeechKit",
            key_url=_YANDEX_KEY_URL,
            notes="Размещение в РФ; асинхронное распознавание до 4 ч / 1 ГБ",
            rf=True,
            supported=False,
        ),
    ),
    Capability.VISION: (
        CatalogProvider(
            id="anthropic",
            label="Anthropic (Claude)",
            key_url=_ANTHROPIC_KEY_URL,
            notes="Изображения и PDF до 600 страниц и 32 МБ на запрос",
            rf=False,
            model_covers=True,
            supported=False,
        ),
        CatalogProvider(
            id="openai",
            label="OpenAI",
            key_url=_OPENAI_KEY_URL,
            notes="Изображения в моделях GPT; РФ не поддержана",
            model_covers=True,
            supported=False,
        ),
        CatalogProvider(
            id="gemini",
            label="Google AI Studio (Gemini)",
            key_url="https://aistudio.google.com/apikey",
            notes="РФ не поддержана; бесплатный уровень учит на данных",
            model_covers=True,
            supported=False,
        ),
    ),
    Capability.OCR: (
        CatalogProvider(
            id="anthropic",
            label="Anthropic (Claude)",
            key_url=_ANTHROPIC_KEY_URL,
            notes="Читает PDF сам; на больших сканах дороже специализированного OCR",
            model_covers=True,
            supported=False,
        ),
        CatalogProvider(
            id="mistral",
            label="Mistral OCR",
            key_url="https://console.mistral.ai/api-keys",
            notes="4.1: $4 за 1000 страниц ($5 с аннотациями), 40+ языков, таблицы — markdown",
            supported=False,
        ),
        CatalogProvider(
            id="yandex",
            label="Yandex Vision OCR",
            key_url=_YANDEX_KEY_URL,
            notes="Размещение в РФ; 0,13–1,52 ₽ за страницу, хорошо с русским",
            rf=True,
            supported=False,
        ),
    ),
    Capability.VIDEO_UNDERSTANDING: (
        CatalogProvider(
            id="gemini",
            label="Google AI Studio (Gemini)",
            key_url="https://aistudio.google.com/apikey",
            notes="Видео на вход целиком, ответ с таймкодами; до 3 ч low res; РФ не поддержана",
            model_covers=True,
            supported=False,
        ),
        CatalogProvider(
            id="twelve_labs",
            label="Twelve Labs",
            key_url="https://playground.twelvelabs.io",
            notes="Индексация и поиск по видео; тарифы меняются 04.01.2027",
            supported=False,
        ),
    ),
    Capability.WEB_SEARCH: (
        CatalogProvider(
            id="tavily",
            label="Tavily",
            key_url="https://app.tavily.com",
            free_tier=_FREE_TAVILY,
            notes="$0,008 за кредит сверх; поиск для агентов",
            supported=True,
        ),
        CatalogProvider(
            id="brave",
            label="Brave Search API",
            key_url="https://api-dashboard.search.brave.com",
            free_tier=_FREE_BRAVE,
            notes="$5 за 1000 запросов; собственный индекс; Google CSE закрывается 01.01.2027",
            supported=True,
        ),
        CatalogProvider(
            id="exa",
            label="Exa",
            key_url="https://dashboard.exa.ai/api-keys",
            free_tier=_FREE_EXA,
            notes="Поиск по смыслу и короткое содержимое страниц",
            supported=True,
        ),
        CatalogProvider(
            id="anthropic",
            label="Anthropic (Claude)",
            key_url=_ANTHROPIC_KEY_URL,
            notes="$10 за 1000 поисков; отдельный ключ не нужен — поиск делает модель",
            model_covers=True,
            supported=False,
        ),
    ),
    Capability.WEB_FETCH: (
        CatalogProvider(
            id="jina",
            label="Jina Reader",
            key_url="https://jina.ai/reader",
            free_tier=_FREE_JINA,
            notes="https://r.jina.ai/<адрес> превращает страницу в markdown",
            supported=True,
        ),
        CatalogProvider(
            id="firecrawl",
            label="Firecrawl",
            key_url="https://www.firecrawl.dev/app/api-keys",
            free_tier=_FREE_FIRECRAWL,
            notes="Страница → markdown, основной текст без меню и рекламы",
            supported=True,
        ),
        CatalogProvider(
            id="anthropic",
            label="Anthropic (Claude)",
            key_url=_ANTHROPIC_KEY_URL,
            notes="Серверный web_fetch читает только адреса, уже появившиеся в разговоре",
            model_covers=True,
            supported=False,
        ),
    ),
    Capability.TTS: (
        CatalogProvider(
            id="elevenlabs",
            label="ElevenLabs",
            key_url="https://elevenlabs.io/app/settings/api-keys",
            notes="Тот же ключ, что Scribe; озвучка вопросов и резюме",
            supported=False,
        ),
        CatalogProvider(
            id="openai",
            label="OpenAI TTS",
            key_url=_OPENAI_KEY_URL,
            notes="РФ не поддержана",
            model_covers=True,
            supported=False,
        ),
        CatalogProvider(
            id="yandex",
            label="Yandex SpeechKit",
            key_url=_YANDEX_KEY_URL,
            notes="Размещение в РФ",
            rf=True,
            supported=False,
        ),
    ),
}

# Что закрывает ключ модели без отдельного ключа: подсказка в карточке возможности.
_MODEL_COVERAGE: dict[Capability, str | None] = {
    Capability.LLM: None,
    Capability.SPEECH_TO_TEXT: "Ключ OpenAI умеет распознавание речи; Claude аудио не принимает",
    Capability.OCR: (
        "Claude читает PDF сам (до 600 страниц и 32 МБ на запрос); отдельный OCR дешевле "
        "на больших сканах"
    ),
    Capability.VISION: "Ключи Claude, OpenAI и Gemini принимают изображения",
    Capability.VIDEO_UNDERSTANDING: "Gemini принимает видео целиком; Claude — только через кадры",
    Capability.WEB_SEARCH: (
        "У Claude — серверный web_search: оплата за поиск, отдельный ключ не нужен"
    ),
    Capability.WEB_FETCH: (
        "У Claude — серверный web_fetch для адресов, уже появившихся в разговоре"
    ),
    Capability.TTS: "У OpenAI есть озвучка; отдельный ключ не обязателен",
}


class ToolCatalogService:
    """Каталог провайдеров; поддержку в коде подтверждает реестр адаптеров."""

    def __init__(self, registry: AdapterRegistry) -> None:
        self._registry = registry

    def catalog(self) -> ToolCatalog:
        """Карточки всех возможностей с датой проверки данных и поддержкой в коде."""
        cards: list[CatalogCapability] = []
        for capability in Capability:
            providers = tuple(
                replace(
                    provider,
                    supported=provider.supported or self._supported(capability, provider.id),
                )
                for provider in _PROVIDERS.get(capability, ())
            )
            cards.append(
                CatalogCapability(
                    capability=capability,
                    providers=providers,
                    model_coverage=_MODEL_COVERAGE.get(capability),
                )
            )
        return ToolCatalog(checked_on=CATALOG_CHECKED_ON, capabilities=tuple(cards))

    def _supported(self, capability: Capability, provider: str) -> bool:
        """Есть ли рабочие вызовы провайдера: LLM — особым списком, остальное — реестром.

        У контрактов (Mistral OCR, Yandex Vision) ключ можно сохранить, но вызовов нет: для
        каталога это `supported=false`, иначе интерфейс предложил бы неработающий инструмент.
        """
        if capability is Capability.LLM:
            return provider in USER_PROVIDERS
        return self._registry.implements(capability, provider)


__all__ = [
    "CATALOG_CHECKED_ON",
    "CatalogCapability",
    "CatalogProvider",
    "ToolCatalog",
    "ToolCatalogService",
]
