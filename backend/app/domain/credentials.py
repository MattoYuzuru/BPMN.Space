"""Ключи моделей пользователя (ADR-0011): чистая модель без ввода-вывода."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

MAX_LABEL_CHARS = 60
MAX_CREDENTIALS_PER_USER = 20
_MIN_HINT_KEY_CHARS = 12


@dataclass(slots=True, kw_only=True)
class LlmCredential:
    """Ключ провайдера. `encrypted_key` — шифртекст; открытый ключ нигде не хранится."""

    id: UUID
    user_id: UUID
    provider: str
    label: str
    base_url: str | None
    encrypted_key: bytes
    key_hint: str
    default_model: str | None
    is_default: bool
    created_at: datetime
    last_used_at: datetime | None = None
    last_error: str | None = None


def key_hint(api_key: str) -> str:
    """Последние 4 символа — чтобы узнать ключ в списке; короткие ключи не раскрываем."""
    return api_key[-4:] if len(api_key) >= _MIN_HINT_KEY_CHARS else ""
