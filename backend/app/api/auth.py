"""Пользовательские маршруты и серверные cookie-сессии через FastAPI Users."""

# FastAPI's dependency injection requires Depends(...) as defaults on these providers.
# ruff: noqa: B008

import secrets
from base64 import urlsafe_b64encode
from collections.abc import AsyncGenerator
from datetime import datetime
from hashlib import sha256
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin
from fastapi_users.authentication import AuthenticationBackend, CookieTransport
from fastapi_users.authentication.strategy.db import AccessTokenDatabase, DatabaseStrategy
from fastapi_users.schemas import BaseUser, BaseUserCreate
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyAccessTokenDatabase
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.infra.db_models import AccessTokenRow, UserRow

settings = get_settings()
SESSION_MAX_AGE = 60 * 60 * 24 * 14
SESSION_COOKIE = "arkhitektor_session"
CSRF_COOKIE = "arkhitektor_csrf"


class UserCreate(BaseUserCreate):
    """Регистрация по адресу почты и паролю."""

    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=12, max_length=128)

    @model_validator(mode="before")
    @classmethod
    def prevent_privileged_flags(cls, value):
        if isinstance(value, dict) and {"is_active", "is_superuser", "is_verified"} & value.keys():
            raise ValueError("Поля статуса учётной записи задаёт сервер")
        return value

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        schema = handler(core_schema)
        properties = schema.get("properties", {})
        for field in ("is_active", "is_superuser", "is_verified"):
            properties.pop(field, None)
        schema["properties"] = properties
        schema["required"] = [field for field in schema.get("required", []) if field in properties]
        return schema


class UserRead(BaseUser[UUID]):
    """Публичный профиль; пароль и внутренние признаки не выдаются."""

    is_active: bool = Field(default=True, exclude=True)
    is_superuser: bool = Field(default=False, exclude=True)
    is_verified: bool = Field(default=False, exclude=True)

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        schema = handler(core_schema)
        properties = schema.get("properties", {})
        for field in ("is_active", "is_superuser", "is_verified"):
            properties.pop(field, None)
        schema["properties"] = properties
        return schema


async def _session(request: Request) -> AsyncGenerator[AsyncSession]:
    database = request.app.state.container.database
    if database is None:
        raise HTTPException(status_code=503, detail="Для учётных записей требуется PostgreSQL")
    async with database.sessions() as session:
        yield session


async def get_user_db(session: AsyncSession = Depends(_session)):
    yield SQLAlchemyUserDatabase(session, UserRow)


async def get_access_token_db(
    session: AsyncSession = Depends(_session),
) -> AsyncGenerator[SQLAlchemyAccessTokenDatabase[AccessTokenRow]]:
    yield HashedAccessTokenDatabase(session, AccessTokenRow)


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


class UserManager(UUIDIDMixin, BaseUserManager[UserRow, UUID]):
    """User lifecycle остаётся в библиотеке; приложение задаёт только адаптер БД."""


async def get_user_manager(user_db=Depends(get_user_db)):
    yield UserManager(user_db)


def get_database_strategy(
    token_db: AccessTokenDatabase[AccessTokenRow] = Depends(get_access_token_db),
) -> DatabaseStrategy[UserRow, UUID, AccessTokenRow]:
    return DatabaseStrategy(token_db, lifetime_seconds=SESSION_MAX_AGE)


cookie_transport = CookieTransport(
    cookie_name=SESSION_COOKIE,
    cookie_max_age=SESSION_MAX_AGE,
    cookie_secure=settings.app_env.lower() in {"prod", "production"},
    cookie_httponly=True,
    cookie_samesite="lax",
)
auth_backend = AuthenticationBackend(
    name="session",
    transport=cookie_transport,
    get_strategy=get_database_strategy,
)
fastapi_users = FastAPIUsers[UserRow, UUID](get_user_manager, [auth_backend])
optional_user = fastapi_users.current_user(active=True, optional=True)
required_user = fastapi_users.current_user(active=True)
OptionalUserDep = Annotated[UserRow | None, Depends(optional_user)]
RequiredUserDep = Annotated[UserRow, Depends(required_user)]

router = APIRouter(tags=["auth"])
router.include_router(fastapi_users.get_auth_router(auth_backend), prefix="/auth/session")
router.include_router(fastapi_users.get_register_router(UserRead, UserCreate), prefix="/auth")


@router.get("/auth/csrf", tags=["auth"])
async def issue_csrf_token(response: Response) -> dict[str, str]:
    """Выдать double-submit CSRF-токен перед регистрацией, входом и изменяющими запросами."""
    token = secrets.token_urlsafe(32)
    response.set_cookie(
        CSRF_COOKIE,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=False,
        secure=settings.app_env.lower() in {"prod", "production"},
        samesite="lax",
        path="/",
    )
    return {"csrf_token": token}


@router.get("/auth/me", response_model=UserRead, tags=["auth"])
async def get_me(user: RequiredUserDep) -> UserRow:
    return user


class SessionState(BaseModel):
    """Состояние входа для клиента: всегда 200, чтобы не путать «гость» с ошибкой сети."""

    auth_enabled: bool = Field(description="false — стенд без аккаунтов, вход не нужен")
    user: UserRead | None = Field(description="Текущий пользователь; null — гость")


@router.get("/auth/session", response_model=SessionState, tags=["auth"])
async def get_session_state(request: Request, user: OptionalUserDep) -> SessionState:
    return SessionState(
        auth_enabled=request.app.state.auth_enabled,
        user=UserRead.model_validate(user, from_attributes=True) if user else None,
    )
