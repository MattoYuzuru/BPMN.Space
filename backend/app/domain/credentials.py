"""Ключи пользователей по типам задач (RFC-0006): чистая модель без ввода-вывода.

Раньше здесь был ключ модели (ADR-0011). Теперь один ключ закрывает одну или несколько
возможностей: LLM, распознавание речи, OCR, vision, видео, поиск и чтение страниц, TTS.
Открытого ключа нет — только шифртекст Fernet, подсказка и метаданные маршрутизации:
приоритет, включённость, лимит, отметка исчерпания и класс последней ошибки.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.capabilities import Capability, CredentialKind, capabilities_for_kinds

MAX_LABEL_CHARS = 60
MAX_CREDENTIALS_PER_USER = 20
_MAX_HINT_KEY_CHARS = 12
DEFAULT_PRIORITY = 100
MAX_PRIORITY = 1000
MAX_ERROR_CHARS = 500
_MIN_HINT_KEY_CHARS = 12
# Поля необязательного месячного лимита ключа: минуты, запросы, деньги.
MONTHLY_LIMIT_FIELDS = frozenset({"minutes", "requests", "cost_usd"})


@dataclass(slots=True, kw_only=True)
class Credential:
    """Ключ провайдера для одной или нескольких возможностей.

    `encrypted_key` — шифртекст; открытый ключ нигде не хранится. `is_default` имеет смысл
    только для типа `llm`: он задаёт ключ модели по умолчанию. Остальные поля — маршрутизация:
    ключи перебираются по возрастанию `priority`, выключенные и исчерпанные пропускаются.
    """

    id: UUID
    user_id: UUID
    provider: str
    label: str
    encrypted_key: bytes
    key_hint: str
    created_at: datetime
    kinds: tuple[CredentialKind, ...] = (CredentialKind.LLM,)
    base_url: str | None = None
    default_model: str | None = None
    is_default: bool = False
    priority: int = DEFAULT_PRIORITY
    enabled: bool = True
    monthly_limit: dict[str, float] | None = None
    exhausted_until: datetime | None = None
    last_error_code: str | None = None
    last_used_at: datetime | None = None
    last_error: str | None = None

    @property
    def capabilities(self) -> tuple[Capability, ...]:
        return capabilities_for_kinds(self.kinds)

    @property
    def is_llm(self) -> bool:
        return CredentialKind.LLM in self.kinds

    def covers(self, capability: Capability) -> bool:
        return capability in self.capabilities

    def is_exhausted(self, now: datetime) -> bool:
        """Ключ временно исключён из перебора: провайдер сообщил об исчерпанной квоте."""
        return self.exhausted_until is not None and self.exhausted_until > now


# Прежнее имя ключа модели (ADR-0011): осталось для совместимости импортов и старых тестов.
LlmCredential = Credential


def key_hint(api_key: str) -> str:
    """Последние 4 символа — чтобы узнать ключ в списке; короткие ключи не раскрываем."""
    return api_key[-4:] if len(api_key) >= _MIN_HINT_KEY_CHARS else ""


def checked_monthly_limit(value: dict[str, float] | None) -> dict[str, float] | None:
    """Проверяет необязательный лимит ключа: только известные поля, каждое больше нуля."""
    if value is None:
        return None
    unknown = set(value) - MONTHLY_LIMIT_FIELDS
    if unknown:
        raise ValueError(f"Неизвестные поля лимита: {', '.join(sorted(unknown))}")
    checked = {name: float(amount) for name, amount in value.items()}
    if not checked:
        raise ValueError("Лимит пуст: укажите хотя бы одно из полей")
    if any(amount <= 0 for amount in checked.values()):
        raise ValueError("Лимит должен быть больше нуля")
    return checked
