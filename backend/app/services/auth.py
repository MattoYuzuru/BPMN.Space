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

from fastapi import Depends, HTTPException, Request, status
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin
from fastapi_users.authentication import AuthenticationBackend, CookieTransport
from fastapi_users.authentication.strategy.db import AccessTokenDatabase, DatabaseStrategy
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyAccessTokenDatabase
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import HTTPConnection

from app.infra.db_models import AccessTokenRow, UserRow
from app.services.api_tokens import (
    INVALID_ACCESS_MESSAGE,
    bearer_secret,
    check_route_policy,
    remember_api_token,
)
from app.services.errors import UnauthorizedError, UnavailableError

__all__ = [
    "SESSION_COOKIE",
    "SESSION_MAX_AGE",
    "UserRow",
    "build_fastapi_users",
    "optional_user",
    "required_user",
    "stream_user",
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
_cookie_user = _users.current_user(active=True, optional=True)


async def token_user(connection: HTTPConnection, secret: str) -> UserRow:
    """Владелец действующего токена доступа (RFC-0007) с проверкой права маршрута.

    Сначала секрет (`401` без подробностей), затем политика маршрута (`403`): неизвестный токен
    не узнаёт, какие права нужны. Пользователь читается в короткой сессии, как у потоков.
    """
    container = connection.app.state.container
    token = await container.api_tokens.authenticate(secret)
    if token is None:
        raise UnauthorizedError(INVALID_ACCESS_MESSAGE)
    check_route_policy(connection, token)
    database = container.database
    if database is None:
        raise UnavailableError("Для учётных записей требуется PostgreSQL")
    async with database.sessions() as session:
        user = await session.get(UserRow, token.user_id)
        if user is None or not user.is_active:
            raise UnauthorizedError(INVALID_ACCESS_MESSAGE)
        session.expunge(user)
    remember_api_token(connection, token)
    return user


async def optional_user(
    request: Request, cookie_user: UserRow | None = Depends(_cookie_user)
) -> UserRow | None:
    """Текущий пользователь: по `Authorization: Bearer` (токен доступа) или по cookie-сессии.

    Заголовок с токеном имеет приоритет: cookie не подменяет неверный или отозванный токен.
    """
    secret = bearer_secret(request)
    if secret is None:
        return cookie_user
    return await token_user(request, secret)


async def required_user(user: UserRow | None = Depends(optional_user)) -> UserRow:
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    return user


async def stream_user(request: HTTPConnection) -> UserRow | None:
    """Проверить cookie HTTP/WS в короткой сессии, не удерживая соединение на время потока.

    HTTP-потоки (SSE) принимают и токен доступа; WebSocket — только cookie: билеты комнаты
    по токену не выдаются.
    """
    if not request.app.state.auth_enabled:
        return None
    secret = bearer_secret(request)
    if secret is not None and request.scope["type"] == "http":
        return await token_user(request, secret)
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
