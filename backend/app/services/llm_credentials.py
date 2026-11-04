"""Совместимость: сервис ключей моделей переехал в `app.services.credentials` (RFC-0006).

Ключ модели — частный случай обобщённого ключа пользователя; здесь осталось прежнее имя класса,
чтобы старые импорты продолжали работать. Новый код использует `CredentialService`.
"""

from app.services.credentials import (
    DEFAULT_ANTHROPIC_MODEL,
    MODELS_ERROR_CACHE_SEC,
    PROVIDER_LABELS,
    CredentialCheck,
    CredentialService,
    LlmCredentialService,
)

__all__ = [
    "DEFAULT_ANTHROPIC_MODEL",
    "MODELS_ERROR_CACHE_SEC",
    "PROVIDER_LABELS",
    "CredentialCheck",
    "CredentialService",
    "LlmCredentialService",
]
