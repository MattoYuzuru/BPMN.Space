"""Базовый контракт адаптеров возможностей (RFC-0006).

Адаптер — реализация одной возможности у одного провайдера. Маршрутизатор создаёт его на
время вызова по ключу пользователя (или по запасному ключу оператора) и закрывает после.
Адаптер не знает, почему выбран именно он, и не логирует открытый ключ.
"""

from typing import Protocol
from uuid import UUID

from app.domain.capabilities import Capability


class CapabilityAdapter(Protocol):
    """Один провайдер одной возможности: проверка ключа и рабочие вызовы."""

    capability: Capability
    provider: str
    model: str | None
    credential_id: UUID | None

    async def check(self) -> str:
        """Проверяет ключ дешёвым запросом; возвращает короткую подпись успеха.

        Отказ — `CapabilityError` с классом: `auth` — ключ отклонён, `transient` — провайдер
        недоступен, `unsupported` — проверка для этого типа ключей пока не реализована.
        """
        ...

    async def aclose(self) -> None:
        """Закрывает HTTP-соединения адаптера."""
        ...
