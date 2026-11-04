"""Возможности инструментов и классы ошибок маршрутизации (RFC-0006).

Возможность (capability) — тип задачи с единым контрактом: модель просит «расшифруй запись»,
а не «вызови Deepgram». Пользователь привязывает к возможности ключи, сервер выбирает реализацию.
Чистый домен: никакого ввода-вывода, только идентификаторы, подписи и структурные результаты.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

CAPABILITIES_DESCRIPTION = "Возможности инструментов: типы задач, которые закрываются ключами"


class CredentialKind(StrEnum):
    """Тип задачи, который закрывает ключ. Один ключ может закрывать несколько типов."""

    LLM = "llm"
    SPEECH_TO_TEXT = "speech_to_text"
    OCR = "ocr"
    VISION = "vision"
    VIDEO = "video"
    WEB_SEARCH = "web_search"
    WEB_FETCH = "web_fetch"
    TTS = "tts"


class Capability(StrEnum):
    """Возможность для инструмента модели (RFC-0006, таблица «Возможности вместо провайдеров»)."""

    LLM = "llm"
    SPEECH_TO_TEXT = "speech_to_text"
    OCR = "ocr"
    VISION = "vision"
    VIDEO_UNDERSTANDING = "video_understanding"
    WEB_SEARCH = "web_search"
    WEB_FETCH = "web_fetch"
    TTS = "tts"


# Соответствие «тип ключа → возможность». У видео тип ключа короче (`video`), а возможность
# называется `video_understanding`: в настройках показывается тип, модели — возможность.
KIND_CAPABILITIES: dict[CredentialKind, Capability] = {
    CredentialKind.LLM: Capability.LLM,
    CredentialKind.SPEECH_TO_TEXT: Capability.SPEECH_TO_TEXT,
    CredentialKind.OCR: Capability.OCR,
    CredentialKind.VISION: Capability.VISION,
    CredentialKind.VIDEO: Capability.VIDEO_UNDERSTANDING,
    CredentialKind.WEB_SEARCH: Capability.WEB_SEARCH,
    CredentialKind.WEB_FETCH: Capability.WEB_FETCH,
    CredentialKind.TTS: Capability.TTS,
}

CAPABILITY_LABELS: dict[Capability, str] = {
    Capability.LLM: "Модели",
    Capability.SPEECH_TO_TEXT: "Распознавание речи",
    Capability.OCR: "Распознавание текста (OCR)",
    Capability.VISION: "Понимание изображений",
    Capability.VIDEO_UNDERSTANDING: "Понимание видео",
    Capability.WEB_SEARCH: "Поиск в интернете",
    Capability.WEB_FETCH: "Чтение страниц",
    Capability.TTS: "Синтез речи",
}

CAPABILITY_DESCRIPTIONS: dict[Capability, str] = {
    Capability.LLM: "Анализ материалов, вопросы и сборка схемы",
    Capability.SPEECH_TO_TEXT: "Запись совещания или голосовая заметка → текст с таймкодами",
    Capability.OCR: "Страницы-сканы документов → текст",
    Capability.VISION: "Кадры и изображения → описание и текст на экране",
    Capability.VIDEO_UNDERSTANDING: "Видео целиком → события с таймкодами",
    Capability.WEB_SEARCH: "Ссылки и выдержки по запросу",
    Capability.WEB_FETCH: "Текст открытой веб-страницы",
    Capability.TTS: "Озвучка вопросов и резюме",
}

# Имя инструмента, которое увидит модель (RFC-0006). Пока инструменты волны 3 не реализованы,
# подписи нужны интерфейсу настроек и будущему агенту.
CAPABILITY_TOOLS: dict[Capability, str] = {
    Capability.LLM: "generate",
    Capability.SPEECH_TO_TEXT: "transcribe",
    Capability.OCR: "ocr_pages",
    Capability.VISION: "describe_images",
    Capability.VIDEO_UNDERSTANDING: "analyze_video",
    Capability.WEB_SEARCH: "search_web",
    Capability.WEB_FETCH: "read_url",
    Capability.TTS: "speak",
}

KIND_LABELS: dict[CredentialKind, str] = {
    CredentialKind.LLM: "Модель",
    CredentialKind.SPEECH_TO_TEXT: "Распознавание речи",
    CredentialKind.OCR: "OCR",
    CredentialKind.VISION: "Изображения",
    CredentialKind.VIDEO: "Видео",
    CredentialKind.WEB_SEARCH: "Веб-поиск",
    CredentialKind.WEB_FETCH: "Чтение страниц",
    CredentialKind.TTS: "Синтез речи",
}


def capabilities_for_kinds(kinds: tuple[CredentialKind, ...]) -> tuple[Capability, ...]:
    """Возможности ключа без повторов, в порядке объявления типов."""
    found: list[Capability] = []
    for kind in kinds:
        capability = KIND_CAPABILITIES[kind]
        if capability not in found:
            found.append(capability)
    return tuple(found)


def kinds_for_capability(capability: Capability) -> tuple[CredentialKind, ...]:
    """Типы ключей, закрывающие возможность."""
    return tuple(kind for kind, value in KIND_CAPABILITIES.items() if value is capability)


class ErrorClass(StrEnum):
    """Класс отказа провайдера (RFC-0006, «Маршрутизация, повторы и отказы»).

    Модели и пользователю уходит класс, а не текст провайдера: по классу решается, повторять
    ли запрос, переключать ли ключ и что написать в техническом вопросе.
    """

    TRANSIENT = "transient"
    QUOTA_EXHAUSTED = "quota_exhausted"
    AUTH = "auth"
    UNSUPPORTED = "unsupported"
    FATAL = "fatal"


# Понятные пользователю причины: класс — основа технического вопроса (RFC-0006).
ERROR_CLASS_MESSAGES: dict[ErrorClass, str] = {
    ErrorClass.TRANSIENT: "Провайдер временно недоступен",
    ErrorClass.QUOTA_EXHAUSTED: "У ключа закончилась квота",
    ErrorClass.AUTH: "Ключ отклонён провайдером",
    ErrorClass.UNSUPPORTED: "Провайдер не принимает этот материал",
    ErrorClass.FATAL: "Ошибка провайдера",
}

# Причина результата, когда ключа под возможность нет вовсе.
REASON_CAPABILITY_MISSING = "capability_missing"
REASON_SERVER_UNAVAILABLE = "server_unavailable"


class CapabilityError(Exception):
    """Отказ провайдера с классом для маршрутизатора.

    Сообщение — для пользователя, на русском; тело и заголовки ответа провайдера сюда не
    попадают (они могут содержать данные запроса). `retry_after_sec` — пауза из заголовка.
    """

    def __init__(
        self,
        error_class: ErrorClass,
        message: str,
        *,
        retry_after_sec: float | None = None,
        alternatives: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.error_class = error_class
        self.message = message
        self.retry_after_sec = retry_after_sec
        self.alternatives = alternatives
        # Сколько попыток ключа уже потрачено: заполняет маршрутизатор для структурного итога.
        self.attempts = 1


@dataclass(frozen=True, slots=True, kw_only=True)
class CapabilityOutcome:
    """Структурный результат работы возможности: что сделано, что нет и почему.

    Модель получает `{status, reason, capability, done, remaining, alternatives}` и сама решает,
    продолжить с тем, что есть, взять запасной путь или задать технический вопрос. Текст
    провайдера в результат не входит.
    """

    capability: Capability
    # `ok` — получилось; `unavailable` — ни один ключ не сработал; `failed` — фатальный отказ.
    status: str
    reason: str | None = None
    done: str | None = None
    remaining: str | None = None
    alternatives: tuple[str, ...] = ()
    provider: str | None = None
    model: str | None = None
    attempts: int = 0
    message: str | None = None
    credential_id: UUID | None = None  # внутреннее: для учёта и настроек, наружу не уходит

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_json(self) -> dict[str, Any]:
        """Форма для предупреждений, `derivation.params` и будущих технических вопросов."""
        return {
            "capability": self.capability.value,
            "status": self.status,
            "reason": self.reason,
            "done": self.done,
            "remaining": self.remaining,
            "alternatives": list(self.alternatives),
            "provider": self.provider,
            "model": self.model,
            "attempts": self.attempts,
        }


class CapabilityUnavailableError(Exception):
    """Возможность не выполнена; несёт структурный результат, а не текст провайдера."""

    def __init__(self, outcome: CapabilityOutcome) -> None:
        self.outcome = outcome
        message = outcome.message
        if message is None:
            try:
                message = ERROR_CLASS_MESSAGES[ErrorClass(outcome.reason)]
            except (TypeError, ValueError):
                message = "Возможность недоступна"
        super().__init__(message)


@dataclass(frozen=True, slots=True, kw_only=True)
class CapabilityIncident:
    """Событие «возможность не выполнена» для технических вопросов (RFC-0006 шаг 2).

    Источник сохраняет структурный результат и понятный текст, а приёмник
    (`CapabilityIncidentSink`) превращает событие в технический вопрос проекта. В приложении это
    `services/capability_incidents.py` поверх `TechnicalQuestionService`; подпись остаётся
    точкой расширения для других инструментов.
    """

    project_id: UUID | None
    capability: Capability
    status: str
    reason: str | None
    message: str
    done: str | None = None
    remaining: str | None = None
    alternatives: tuple[str, ...] = ()
    source_id: UUID | None = None
    derivation: dict[str, Any] | None = None


class CapabilityIncidentSink(Protocol):
    """Приёмник событий для технических вопросов; в приложении — мост к волне 2B."""

    async def report(self, incident: CapabilityIncident) -> None: ...
