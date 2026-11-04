"""Контракт каталога провайдеров для настроек «Инструменты» (RFC-0006, шаг 6)."""

from datetime import date

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.api.schemas.credentials import CapabilityLiteral, CredentialKindLiteral
from app.services.tool_catalog import (
    CatalogCapability,
    CatalogProvider,
    ToolCatalog,
)


class ToolCatalogProvider(ApiModel):
    """Провайдер: где взять ключ, бесплатный уровень и поддержка в коде."""

    id: str
    label: str
    key_url: str | None = Field(
        default=None,
        description="Страница, где взять ключ; null — ключ и адрес выдаёт ваш сервер",
    )
    free_tier: str | None = Field(default=None, description="Что даёт бесплатный уровень")
    notes: str | None = Field(default=None, description="Ограничения и особенности провайдера")
    rf: bool = Field(description="Данные размещаются в РФ")
    model_covers: bool = Field(
        description="Возможность закрывает ключ модели, отдельный ключ не нужен"
    )
    supported: bool = Field(description="Есть адаптер в коде: такой ключ можно добавить")

    @classmethod
    def of(cls, provider: CatalogProvider) -> "ToolCatalogProvider":
        return cls(
            id=provider.id,
            label=provider.label,
            key_url=provider.key_url,
            free_tier=provider.free_tier,
            notes=provider.notes,
            rf=provider.rf,
            model_covers=provider.model_covers,
            supported=provider.supported,
        )


class ToolCatalogCapability(ApiModel):
    """Карточка возможности: что делает, каким инструментом видит модель и чем закрыть."""

    capability: CapabilityLiteral
    label: str
    description: str
    tool: str = Field(description="Имя инструмента, которое увидит модель")
    kinds: list[CredentialKindLiteral] = Field(description="Типы ключей, закрывающие возможность")
    model_coverage: str | None = Field(
        default=None, description="Что закрывает ключ модели без отдельного ключа"
    )
    providers: list[ToolCatalogProvider]

    @classmethod
    def of(cls, card: CatalogCapability) -> "ToolCatalogCapability":
        return cls(
            capability=card.capability.value,
            label=card.label,
            description=card.description,
            tool=card.tool,
            kinds=[kind.value for kind in card.kinds],
            model_coverage=card.model_coverage,
            providers=[ToolCatalogProvider.of(provider) for provider in card.providers],
        )


class ToolCatalogResponse(ApiModel):
    """Каталог провайдеров с датой проверки; дополняет карточки `/me/credentials`."""

    checked_on: date = Field(description="Дата проверки цен, бесплатных уровней и ссылок")
    capabilities: list[ToolCatalogCapability]

    @classmethod
    def of(cls, catalog: ToolCatalog) -> "ToolCatalogResponse":
        return cls(
            checked_on=catalog.checked_on,
            capabilities=[ToolCatalogCapability.of(card) for card in catalog.capabilities],
        )


__all__ = [
    "ToolCatalogCapability",
    "ToolCatalogProvider",
    "ToolCatalogResponse",
]
