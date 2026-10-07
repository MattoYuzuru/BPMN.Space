"""Подключение FastAPI Users: пользователи, хеш-сессии в БД, зависимости текущего пользователя.

HTTP-маршруты и схемы живут в `app/api/auth.py`; здесь только то, что знает про хранилище.
"""

# FastAPI требует Depends(...) в значениях по умолчанию у этих провайдеров.
# ruff: noqa: B008

from base64 import urlsafe_b64encode
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import UUID

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin
from fastapi_users.authentication import AuthenticationBackend, CookieTransport
from fastapi_users.authentication.strategy.db import AccessTokenDatabase, DatabaseStrategy
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyAccessTokenDatabase
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import HTTPConnection

from app.infra.db_models import AccessTokenRow, UserRow
from app.services.errors import UnavailableError

__all__ = [
    "SESSION_COOKIE",
    "SESSION_MAX_AGE",
    "UserRow",
    "build_fastapi_users",
    "optional_user",
    "required_user",
]

SESSION_MAX_AGE = 60 * 60 * 24 * 14
SESSION_COOKIE = "arkhitektor_session"


async def _session(request: Request) -> AsyncGenerator[AsyncSession]:
    database = request.app.state.container.database
    if database is None:
        raise UnavailableError("Для учётных записей требуется PostgreSQL")
    async with database.sessions() as session:
        yield session


async def get_user_db(session: AsyncSession = Depends(_session)):
    yield SQLAlchemyUserDatabase(session, UserRow)


class HashedAccessTokenDatabase(SQLAlchemyAccessTokenDatabase[AccessTokenRow]):
    """Хранить только хеш сессии: утечка БД не даёт готовые cookie для повтора."""

    @staticmethod
    def _digest(token: str) -> str:
        return urlsafe_b64encode(sha256(token.encode()).digest()).rstrip(b"=").decode()

    async def create(self, create_dict: dict[str, Any]) -> AccessTokenRow:
        raw_token = create_dict["token"]
        row = await super().create({**create_dict, "token": self._digest(raw_token)})
        self.session.expunge(row)
        row.token = raw_token
        return row

    async def get_by_token(
        self, token: str, max_age: datetime | None = None
    ) -> AccessTokenRow | None:
        return await super().get_by_token(self._digest(token), max_age)


async def get_access_token_db(
    session: AsyncSession = Depends(_session),
) -> AsyncGenerator[SQLAlchemyAccessTokenDatabase[AccessTokenRow]]:
    yield HashedAccessTokenDatabase(session, AccessTokenRow)


class UserManager(UUIDIDMixin, BaseUserManager[UserRow, UUID]):
    """Жизненный цикл пользователя остаётся в библиотеке; приложение задаёт только адаптер БД."""


async def get_user_manager(user_db=Depends(get_user_db)):
    yield UserManager(user_db)


def get_database_strategy(
    token_db: AccessTokenDatabase[AccessTokenRow] = Depends(get_access_token_db),
) -> DatabaseStrategy[UserRow, UUID, AccessTokenRow]:
    return DatabaseStrategy(token_db, lifetime_seconds=SESSION_MAX_AGE)


def build_fastapi_users(*, cookie_secure: bool) -> tuple[FastAPIUsers[UserRow, UUID], Any]:
    """FastAPI Users и backend сессии; `Secure` у cookie задаётся настройкой, не константой."""
    backend = AuthenticationBackend(
        name="session",
        transport=CookieTransport(
            cookie_name=SESSION_COOKIE,
            cookie_max_age=SESSION_MAX_AGE,
            cookie_secure=cookie_secure,
            cookie_httponly=True,
            cookie_samesite="lax",
        ),
        get_strategy=get_database_strategy,
    )
    return FastAPIUsers[UserRow, UUID](get_user_manager, [backend]), backend


# Зависимости текущего пользователя читают cookie по имени и не зависят от флага `Secure`.
_users, _ = build_fastapi_users(cookie_secure=False)
optional_user = _users.current_user(active=True, optional=True)
required_user = _users.current_user(active=True)


async def stream_user(request: HTTPConnection) -> UserRow | None:
    """Проверить cookie HTTP/WS в короткой сессии, не удерживая соединение на время потока."""
    if not request.app.state.auth_enabled:
        return None
    token = request.cookies.get(SESSION_COOKIE)
    if token is None:
        return None
    database = request.app.state.container.database
    if database is None:
        raise UnavailableError("Для учётных записей требуется PostgreSQL")

    max_age = datetime.now(UTC) - timedelta(seconds=SESSION_MAX_AGE)
    async with database.sessions() as session:
        access_token = await HashedAccessTokenDatabase(session, AccessTokenRow).get_by_token(
            token, max_age
        )
        if access_token is None:
            return None
        user = await session.get(UserRow, access_token.user_id)
        if user is None or not user.is_active:
            return None
        session.expunge(user)
        return user
