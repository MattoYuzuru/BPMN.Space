"""Контракт ключей по типам задач (RFC-0006). Открытый ключ принимается один раз."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr, model_validator

from app.api.schemas.common import ApiModel
from app.domain.credentials import Credential as DomainCredential
from app.services.credentials import (
    CapabilityCard,
)
from app.services.credentials import (
    CredentialCheck as ServiceCheck,
)

WireApi = Literal["chat_completions", "responses"]
CredentialKindLiteral = Literal[
    "llm", "speech_to_text", "ocr", "vision", "video", "web_search", "web_fetch", "tts"
]
CapabilityLiteral = Literal[
    "llm",
    "speech_to_text",
    "ocr",
    "vision",
    "video_understanding",
    "web_search",
    "web_fetch",
    "tts",
]


class MonthlyLimit(ApiModel):
    """Необязательный месячный лимит ключа: минуты, запросы или деньги."""

    minutes: float | None = Field(default=None, gt=0)
    requests: int | None = Field(default=None, gt=0)
    cost_usd: float | None = Field(default=None, gt=0)


class Credential(ApiModel):
    id: UUID
    kinds: list[CredentialKindLiteral]
    provider: str
    label: str
    base_url: str | None = Field(description="Только у совместимого провайдера")
    wire_api: WireApi | None = Field(
        default=None,
        description=(
            "Протокол совместимого сервера: chat_completions или responses (ADR-0013); "
            "null — Chat Completions"
        ),
    )
    key_hint: str = Field(description="Последние 4 символа ключа; пусто у коротких ключей")
    default_model: str | None
    priority: int = Field(description="Меньше — раньше в переборе")
    enabled: bool
    monthly_limit: MonthlyLimit | None
    exhausted_until: datetime | None = Field(
        description="Ключ отдыхает: провайдер сообщил об исчерпанной квоте"
    )
    last_error_code: str | None = Field(description="Класс последней ошибки (RFC-0006)")
    last_error: str | None = Field(description="Понятный текст последней ошибки")
    is_default: bool = Field(description="Ключ модели по умолчанию (только для `llm`)")
    capabilities: list[CapabilityLiteral] = Field(description="Возможности, которые закрывает ключ")
    created_at: datetime
    last_used_at: datetime | None

    @classmethod
    def of(cls, item: DomainCredential) -> "Credential":
        limit = item.monthly_limit
        return cls(
            id=item.id,
            kinds=[kind.value for kind in item.kinds],
            provider=item.provider,
            label=item.label,
            base_url=item.base_url,
            wire_api=item.wire_api,  # type: ignore[arg-type]
            key_hint=item.key_hint,
            default_model=item.default_model,
            priority=item.priority,
            enabled=item.enabled,
            monthly_limit=MonthlyLimit(
                minutes=limit.get("minutes"),
                requests=int(limit["requests"]) if "requests" in limit else None,
                cost_usd=limit.get("cost_usd"),
            )
            if limit
            else None,
            exhausted_until=item.exhausted_until,
            last_error_code=item.last_error_code,
            last_error=item.last_error,
            is_default=item.is_default,
            capabilities=[capability.value for capability in item.capabilities],
            created_at=item.created_at,
            last_used_at=item.last_used_at,
        )


class CredentialProvider(ApiModel):
    id: str
    label: str


class CapabilityCardSchema(ApiModel):
    """Карточка возможности для «Настроек → Инструменты»."""

    capability: CapabilityLiteral
    label: str
    description: str
    tool: str = Field(description="Имя инструмента, которое увидит модель")
    kinds: list[CredentialKindLiteral]
    providers: list[CredentialProvider]
    keys: int = Field(description="Рабочих ключей: включённых и не исчерпанных")
    available: bool
    last_error_code: str | None = None

    @classmethod
    def of(cls, card: CapabilityCard) -> "CapabilityCardSchema":
        return cls(
            capability=card.capability.value,
            label=card.label,
            description=card.description,
            tool=card.tool,
            kinds=[kind.value for kind in card.kinds],
            providers=[
                CredentialProvider(id=provider.id, label=provider.label)
                for provider in card.providers
            ],
            keys=card.keys,
            available=card.available,
            last_error_code=card.last_error_code,
        )


class CredentialList(ApiModel):
    items: list[Credential]
    storage_available: bool = Field(
        description="false — на сервере не задан CREDENTIALS_ENCRYPTION_KEY, ключи не принимаются"
    )
    capabilities: list[CapabilityCardSchema] = Field(
        description="Карточки всех возможностей: какие ключи есть и какие нужны"
    )


class CredentialCreate(ApiModel):
    kinds: list[CredentialKindLiteral] = Field(
        min_length=1, description="Типы задач, которые закрывает ключ: llm, speech_to_text, …"
    )
    provider: str = Field(max_length=32)
    label: str | None = Field(default=None, max_length=60)
    api_key: SecretStr = Field(description="Принимается один раз; сохраняется зашифрованным")
    base_url: str | None = Field(default=None, max_length=500)
    wire_api: WireApi | None = Field(
        default=None, description="Только для совместимого провайдера; не задан — chat_completions"
    )
    default_model: str | None = Field(default=None, max_length=128)
    priority: int = Field(default=100, ge=0, le=1000)
    enabled: bool = True
    monthly_limit: MonthlyLimit | None = None
    is_default: bool = Field(default=False, description="Только для ключа модели")


class CredentialUpdate(ApiModel):
    label: str | None = Field(default=None, max_length=60)
    default_model: str | None = Field(default=None, max_length=128)
    is_default: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=1000)
    enabled: bool | None = None
    monthly_limit: MonthlyLimit | None = None
    clear_monthly_limit: bool = False

    @model_validator(mode="after")
    def _checked_limit(self) -> "CredentialUpdate":
        if self.monthly_limit is not None and self.clear_monthly_limit:
            raise ValueError("нельзя одновременно задать и очистить лимит")
        return self


class CredentialCheckResult(ApiModel):
    """Итог проверки ключа: отказ провайдера — `ok=false`, а не ошибка запроса."""

    ok: bool
    detail: str
    capability: CapabilityLiteral | None = None
    last_error_code: str | None = None

    @classmethod
    def of(cls, result: ServiceCheck) -> "CredentialCheckResult":
        return cls(
            ok=result.ok,
            detail=result.detail,
            capability=result.capability.value if result.capability is not None else None,
            last_error_code=result.last_error_code,
        )


def monthly_limit_dict(limit: MonthlyLimit | None) -> dict[str, float] | None:
    """Схема лимита → jsonb-словарь домена; пустые поля не сохраняются."""
    if limit is None:
        return None
    values = limit.model_dump(exclude_none=True)
    return {name: float(amount) for name, amount in values.items()} or None
