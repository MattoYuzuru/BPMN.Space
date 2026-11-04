"""Персональные токены доступа для внешних агентов (RFC-0007): чистая модель без ввода-вывода.

Секрет вида `bps_<случайная строка>` показывается один раз; в БД — только SHA-256 и короткий
префикс для опознания в списке. Права и ограничение проектами сужают то, что владелец токена
может сам в обычной cookie-сессии, и никогда не расширяют его роль в проекте.
"""

import secrets
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from uuid import UUID

TOKEN_PREFIX = "bps_"  # noqa: S105 — формат секрета, а не секрет
_SECRET_BYTES = 32
_DISPLAY_CHARS = 6  # символов после `bps_` в префиксе для опознания
_MIN_SECRET_CHARS = len(TOKEN_PREFIX) + 16
_MAX_SECRET_CHARS = 128
MAX_NAME_CHARS = 80
MAX_ACTIVE_TOKENS_PER_USER = 50
MAX_PROJECTS_PER_TOKEN = 100
DEFAULT_TTL_DAYS = 30
MAX_TTL_DAYS = 365
# `last_used_at` пишется не чаще раза в минуту: запросы агента не превращаются в поток UPDATE.
LAST_USED_RESOLUTION = timedelta(minutes=1)


class ApiScope(StrEnum):
    """Право токена. Пользователь в cookie-сессии имеет все права своей роли, как раньше."""

    PROJECTS_READ = "projects:read"
    PROJECTS_WRITE = "projects:write"
    SOURCES_WRITE = "sources:write"
    SOURCES_DELETE = "sources:delete"
    RUNS_START = "runs:start"
    QUESTIONS_ANSWER = "questions:answer"


SCOPE_LABELS: dict[ApiScope, str] = {
    ApiScope.PROJECTS_READ: "читать проекты, схемы, версии, вопросы и источники",
    ApiScope.PROJECTS_WRITE: "создавать и переименовывать проекты, сохранять схему",
    ApiScope.SOURCES_WRITE: "добавлять и изменять источники",
    ApiScope.SOURCES_DELETE: "удалять источники",
    ApiScope.RUNS_START: "запускать прогоны и помощника (платные вызовы)",
    ApiScope.QUESTIONS_ANSWER: "отвечать на вопросы",
}

# Минимум по умолчанию (RFC-0007, «Безопасность»): чтение и ответы.
DEFAULT_SCOPES: tuple[ApiScope, ...] = (ApiScope.PROJECTS_READ, ApiScope.QUESTIONS_ANSWER)


@dataclass(frozen=True, slots=True)
class TokenPolicy:
    """Что маршрут требует от токена. Маршрут без политики по токену недоступен.

    `scope=None` — достаточно любого действующего токена (например, «кто я»).
    `all_projects=True` — токен не должен быть ограничен проектами (создание нового проекта:
    иначе токен создал бы проект, к которому сам не имеет доступа).
    """

    scope: ApiScope | None
    all_projects: bool = False


@dataclass(slots=True, kw_only=True)
class ApiToken:
    """Токен доступа. `token_hash` — SHA-256 секрета; сам секрет нигде не хранится."""

    id: UUID
    user_id: UUID
    name: str
    token_prefix: str
    token_hash: str
    scopes: tuple[ApiScope, ...]
    # None — все проекты пользователя (в том числе созданные позже).
    project_ids: tuple[UUID, ...] | None
    expires_at: datetime
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    # Токен проверки (RFC-0007 шаг 3): выдан по ссылке reviewer и живёт ровно её область.
    # Ссылка проверяется при каждом запросе: отзыв или истечение ссылки отзывает доступ.
    share_link_id: UUID | None = None
    lane_ids: tuple[str, ...] | None = None

    def is_review(self) -> bool:
        return self.share_link_id is not None

    def is_expired(self, now: datetime) -> bool:
        return self.expires_at <= now

    def is_active(self, now: datetime) -> bool:
        return self.revoked_at is None and not self.is_expired(now)

    def has_scope(self, scope: ApiScope) -> bool:
        return scope in self.scopes

    def allows_project(self, project_id: UUID) -> bool:
        return self.project_ids is None or project_id in self.project_ids

    def needs_touch(self, now: datetime) -> bool:
        return self.last_used_at is None or now - self.last_used_at >= LAST_USED_RESOLUTION


def generate_secret() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(_SECRET_BYTES)


def hash_secret(secret: str) -> str:
    return sha256(secret.encode("utf-8")).hexdigest()


def display_prefix(secret: str) -> str:
    """`bps_` и несколько первых символов: узнать токен в списке, не раскрывая его."""
    return secret[: len(TOKEN_PREFIX) + _DISPLAY_CHARS]


def looks_like_secret(value: str) -> bool:
    """Отсечь заведомо чужие значения без запроса к БД; длина — с запасом на формат."""
    return value.startswith(TOKEN_PREFIX) and _MIN_SECRET_CHARS <= len(value) <= _MAX_SECRET_CHARS


def ordered_scopes(scopes: Iterable[ApiScope]) -> tuple[ApiScope, ...]:
    """Права в порядке перечисления: стабильный ответ API и строки в БД."""
    chosen = set(scopes)
    return tuple(scope for scope in ApiScope if scope in chosen)
