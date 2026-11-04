"""Контракт ключей моделей пользователя. Открытый ключ принимается один раз и не возвращается."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr

from app.api.schemas.common import ApiModel
from app.domain.credentials import LlmCredential as DomainCredential
from app.llm.capabilities import ModelCapabilities

Provider = Literal["anthropic", "openai", "openai_compatible"]


class LlmCredential(ApiModel):
    id: UUID
    provider: Provider
    label: str
    base_url: str | None = Field(description="Только для совместимого провайдера")
    key_hint: str = Field(description="Последние 4 символа ключа; пусто у коротких ключей")
    default_model: str | None
    is_default: bool
    created_at: datetime
    last_used_at: datetime | None
    last_error: str | None = Field(description="Ошибка последнего использования ключа")

    @classmethod
    def of(cls, item: DomainCredential) -> "LlmCredential":
        return cls.model_validate(item)


class LlmCredentialList(ApiModel):
    items: list[LlmCredential]
    storage_available: bool = Field(
        description="false — на сервере не задан CREDENTIALS_ENCRYPTION_KEY, ключи не принимаются"
    )


class LlmCredentialCreate(ApiModel):
    provider: Provider
    label: str | None = Field(default=None, max_length=60)
    api_key: SecretStr = Field(description="Принимается один раз; сохраняется зашифрованным")
    base_url: str | None = Field(default=None, max_length=500)
    default_model: str | None = Field(default=None, max_length=128)
    is_default: bool = False


class LlmCredentialUpdate(ApiModel):
    label: str | None = Field(default=None, max_length=60)
    default_model: str | None = Field(default=None, max_length=128)
    is_default: bool | None = None


Effort = Literal["low", "medium", "high", "xhigh", "max"]


class LlmModelPrices(ApiModel):
    """Цены провайдера в долларах за 1 млн токенов на дату проверки (ориентир, не счёт)."""

    input: float
    output: float
    cache_read: float | None = Field(description="Чтение кеша промпта")
    cache_write: float | None = Field(description="Запись кеша промпта (TTL 5 минут)")
    currency: Literal["USD"] = "USD"
    checked_on: date = Field(description="Когда цены сверены с прайсом провайдера")
    note: str | None = Field(default=None, description="Оговорка: например, порог длины промпта")


class LlmModelCapabilities(ApiModel):
    """Возможности модели: справочник сервера, уточнённый списком моделей провайдера."""

    known: bool = Field(description="false — модель неизвестна, показаны осторожные умолчания")
    context_tokens: int | None = Field(description="Окно контекста; null — неизвестно")
    max_output_tokens: int | None = Field(description="Максимум ответа; null — неизвестно")
    vision: bool
    pdf_input: bool
    tools: bool
    effort_levels: list[Effort] = Field(
        description="Уровни глубины, которые модель принимает; пусто — модель без рассуждения"
    )
    effort_default: Effort | None = Field(
        description="Уровень, который сервер отправит, если в профиле прогона его нет"
    )
    accepts_temperature: bool
    prices: LlmModelPrices | None = None

    @classmethod
    def of(cls, caps: ModelCapabilities) -> "LlmModelCapabilities":
        prices = caps.prices
        return cls(
            known=caps.known,
            context_tokens=caps.context_tokens,
            max_output_tokens=caps.max_output_tokens,
            vision=caps.vision,
            pdf_input=caps.pdf_input,
            tools=caps.tools,
            effort_levels=list(caps.effort_levels),
            effort_default=caps.effort_default,
            accepts_temperature=caps.accepts_temperature,
            prices=LlmModelPrices(
                input=prices.input,
                output=prices.output,
                cache_read=prices.cache_read,
                cache_write=prices.cache_write,
                checked_on=prices.checked_on,
                note=prices.note,
            )
            if prices
            else None,
        )


class LlmModel(ApiModel):
    id: str
    label: str
    capabilities: LlmModelCapabilities


class LlmModelList(ApiModel):
    items: list[LlmModel]
