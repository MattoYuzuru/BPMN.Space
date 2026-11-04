"""Точка входа FastAPI."""

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic.json_schema import models_json_schema

from app.api.auth import CSRF_COOKIE, build_auth_router
from app.api.errors import install_error_handlers
from app.api.limits import BodyLimitMiddleware
from app.api.ratelimit import install_rate_limits
from app.api.v1 import api_router
from app.api.v1.runs import OPENAPI_EXTRA_MODELS
from app.config import Settings, get_settings
from app.container import Container, build_container
from app.infra.seed import build_seed
from app.log_filters import install_log_filters
from app.services.api_tokens import bearer_secret
from app.services.auth import SESSION_COOKIE, optional_user
from app.services.presence import PresenceRegistry


def _openapi(app: FastAPI) -> dict[str, Any]:
    """OpenAPI + схемы SSE-сообщений, которых нет в телах запросов и ответов."""
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    _, extra = models_json_schema(
        [(model, "serialization") for model in OPENAPI_EXTRA_MODELS],
        ref_template="#/components/schemas/{model}",
    )
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    for name, definition in extra.get("$defs", {}).items():
        components.setdefault(name, definition)
    app.openapi_schema = schema
    return schema


def _install_csrf(app: FastAPI, settings: Settings) -> None:
    """Double-submit CSRF для изменяющих запросов API; правила для токенов доступа (RFC-0007)."""
    account_register = settings.api_prefix + "/auth/register"
    account_session = settings.api_prefix + "/auth/session/"

    @app.middleware("http")
    async def csrf_protection(request, call_next):
        path = request.url.path
        unsafe = request.method not in {"GET", "HEAD", "OPTIONS", "TRACE"}
        is_api = path.startswith(settings.api_prefix + "/")
        # Вход, регистрация и выход (FastAPI Users) работают только с cookie: заголовок
        # `Authorization` там не используется и не должен отключать CSRF (RFC-0007).
        account_route = path == account_register or path.startswith(account_session)
        if settings.auth_enabled and account_route and "authorization" in request.headers:
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "Вход, регистрация и выход — только в браузере, без токена доступа"
                },
            )
        # Запрос с `Authorization: Bearer` и без cookie-сессии аутентифицируется только токеном
        # доступа. Чужой сайт не может добавить этот заголовок без CORS-preflight, поэтому
        # double-submit CSRF к таким запросам не применяется. Если cookie-сессия всё же пришла,
        # CSRF проверяется как обычно.
        token_only = bearer_secret(request) is not None and SESSION_COOKIE not in request.cookies
        if settings.auth_enabled and unsafe and is_api and not token_only:
            cookie = request.cookies.get(CSRF_COOKIE)
            header = request.headers.get("x-csrf-token")
            if not cookie or not header or not secrets.compare_digest(cookie, header):
                return JSONResponse(
                    status_code=403, content={"detail": "CSRF-токен отсутствует или не совпадает"}
                )
        return await call_next(request)


def create_app(settings: Settings | None = None, *, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    container = container or build_container(settings)
    install_log_filters()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        database = container.database
        if database:
            recovered_runs = await database.initialize()
            if settings.seed_demo_data:
                await database.seed(build_seed)
            for run_id in recovered_runs:
                container.runs.resume(run_id)
        try:
            yield
        finally:
            await container.spawner.shutdown()
            if database:
                await database.dispose()

    app = FastAPI(
        title="Архитектор BPMN-диаграмм",
        version="0.1.0",
        lifespan=lifespan,
        generate_unique_id_function=lambda route: route.name,
    )
    app.state.container = container
    app.state.auth_enabled = settings.auth_enabled
    app.state.presence = PresenceRegistry()
    if not settings.auth_enabled:
        app.dependency_overrides[optional_user] = lambda: None
    # Лимиты ставим раньше CORS: тогда 429 тоже получает CORS-заголовки.
    install_rate_limits(app, settings)
    # Лимит тела — внутри CORS: ответ 413 тоже получает CORS-заголовки.
    app.add_middleware(BodyLimitMiddleware, settings=settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
    )

    _install_csrf(app, settings)

    shares_prefix = settings.api_prefix + "/shares/"

    @app.middleware("http")
    async def share_privacy(request, call_next):
        """Ответы по ссылке «поделиться»: адрес с секретом не утекает в Referer и поиск."""
        response = await call_next(request)
        if request.url.path.startswith(shares_prefix):
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["X-Robots-Tag"] = "noindex"
        return response

    install_error_handlers(app)
    app.include_router(api_router, prefix=settings.api_prefix)
    app.include_router(build_auth_router(settings), prefix=settings.api_prefix)

    @app.get("/health", tags=["service"])
    async def health() -> dict[str, str]:
        if container.database:
            await container.database.check()
        return {"status": "ok"}

    app.openapi = lambda: _openapi(app)  # type: ignore[method-assign]
    return app


app = create_app()
