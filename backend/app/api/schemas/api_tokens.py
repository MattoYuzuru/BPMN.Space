"""Контракт персональных токенов доступа (RFC-0007). Секрет возвращается только при создании."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.domain.api_tokens import (
    DEFAULT_SCOPES,
    DEFAULT_TTL_DAYS,
    MAX_NAME_CHARS,
    MAX_PROJECTS_PER_TOKEN,
    MAX_TTL_DAYS,
    ApiScope,
)
from app.domain.api_tokens import ApiToken as DomainToken


class ApiToken(ApiModel):
    id: UUID
    name: str
    token_prefix: str = Field(description="`bps_` и первые символы секрета — чтобы узнать токен")
    scopes: list[ApiScope]
    project_ids: list[UUID] | None = Field(description="null — все проекты пользователя")
    expires_at: datetime
    created_at: datetime
    last_used_at: datetime | None = Field(description="С точностью до минуты")
    expired: bool = Field(description="Срок истёк: токен больше не принимается")

    @classmethod
    def of(cls, item: DomainToken, now: datetime) -> "ApiToken":
        return cls(
            id=item.id,
            name=item.name,
            token_prefix=item.token_prefix,
            scopes=list(item.scopes),
            project_ids=list(item.project_ids) if item.project_ids is not None else None,
            expires_at=item.expires_at,
            created_at=item.created_at,
            last_used_at=item.last_used_at,
            expired=item.is_expired(now),
        )


class ApiTokenCreated(ApiToken):
    secret: str = Field(
        description="Секрет `bps_…`: показывается один раз, в БД хранится только SHA-256"
    )


class ApiTokenList(ApiModel):
    items: list[ApiToken]


class ApiTokenCreate(ApiModel):
    name: str = Field(min_length=1, max_length=MAX_NAME_CHARS)
    scopes: list[ApiScope] = Field(
        default_factory=lambda: list(DEFAULT_SCOPES),
        min_length=1,
        description="По умолчанию — чтение проектов и ответы на вопросы",
    )
    project_ids: list[UUID] | None = Field(
        default=None,
        max_length=MAX_PROJECTS_PER_TOKEN,
        description="null — все проекты пользователя, включая созданные позже",
    )
    expires_in_days: int = Field(
        default=DEFAULT_TTL_DAYS,
        ge=1,
        le=MAX_TTL_DAYS,
        description="Срок действия в днях; бессрочных токенов нет",
    )
