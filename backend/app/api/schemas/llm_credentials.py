"""Контракт ключей моделей пользователя. Открытый ключ принимается один раз и не возвращается."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr

from app.api.schemas.common import ApiModel
from app.domain.credentials import LlmCredential as DomainCredential

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


class LlmModel(ApiModel):
    id: str
    label: str


class LlmModelList(ApiModel):
    items: list[LlmModel]
