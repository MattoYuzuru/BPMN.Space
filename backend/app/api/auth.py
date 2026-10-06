"""Маршруты аккаунтов: регистрация, вход по cookie-сессии, CSRF и состояние входа.

Подключение FastAPI Users и хранилище сессий — в `app/services/auth.py`.
"""

import secrets
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from fastapi_users.schemas import BaseUser, BaseUserCreate
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config import Settings
from app.services.auth import (
    SESSION_MAX_AGE,
    UserRow,
    build_fastapi_users,
    optional_user,
    required_user,
    stream_user,
)

CSRF_COOKIE = "arkhitektor_csrf"


class UserCreate(BaseUserCreate):
    """Регистрация по адресу почты и паролю."""

    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=8, max_length=128)

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


OptionalUserDep = Annotated[UserRow | None, Depends(optional_user)]
# SSE может жить долго: проверяем cookie в короткой сессии до запуска потока,
# чтобы соединение БД не удерживалось всё время подписки клиента.
OptionalUserStreamDep = Annotated[UserRow | None, Depends(stream_user, scope="function")]
RequiredUserDep = Annotated[UserRow, Depends(required_user)]


class SessionState(BaseModel):
    """Состояние входа для клиента: всегда 200, чтобы не путать «гость» с ошибкой сети."""

    auth_enabled: bool = Field(description="false — стенд без аккаунтов, вход не нужен")
    user: UserRead | None = Field(description="Текущий пользователь; null — гость")


def build_auth_router(settings: Settings) -> APIRouter:
    """Маршруты `/auth/*`; флаг `Secure` у cookie берётся из настроек приложения."""
    fastapi_users, backend = build_fastapi_users(cookie_secure=settings.cookie_secure)
    router = APIRouter(tags=["auth"])
    router.include_router(fastapi_users.get_auth_router(backend), prefix="/auth/session")
    router.include_router(fastapi_users.get_register_router(UserRead, UserCreate), prefix="/auth")

    @router.get("/auth/csrf")
    async def issue_csrf_token(response: Response) -> dict[str, str]:
        """Выдать double-submit CSRF-токен перед регистрацией, входом и изменяющими запросами."""
        token = secrets.token_urlsafe(32)
        response.set_cookie(
            CSRF_COOKIE,
            token,
            max_age=SESSION_MAX_AGE,
            httponly=False,
            secure=settings.cookie_secure,
            samesite="lax",
            path="/",
        )
        return {"csrf_token": token}

    @router.get("/auth/me", response_model=UserRead)
    async def get_me(user: RequiredUserDep) -> UserRow:
        return user

    @router.get("/auth/session", response_model=SessionState)
    async def get_session_state(request: Request, user: OptionalUserDep) -> SessionState:
        return SessionState(
            auth_enabled=request.app.state.auth_enabled,
            user=UserRead.model_validate(user, from_attributes=True) if user else None,
        )

    return router
