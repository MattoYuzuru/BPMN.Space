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
from app.services.auth import optional_user


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


def create_app(settings: Settings | None = None, *, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    container = container or build_container(settings)
    install_log_filters()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        database = container.database
        if database:
            await database.initialize()
            if settings.seed_demo_data:
                await database.seed(build_seed)
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

    @app.middleware("http")
    async def csrf_protection(request, call_next):
        unsafe = request.method not in {"GET", "HEAD", "OPTIONS", "TRACE"}
        is_api = request.url.path.startswith(settings.api_prefix + "/")
        if settings.auth_enabled and unsafe and is_api:
            cookie = request.cookies.get(CSRF_COOKIE)
            header = request.headers.get("x-csrf-token")
            if not cookie or not header or not secrets.compare_digest(cookie, header):
                return JSONResponse(
                    status_code=403, content={"detail": "CSRF-токен отсутствует или не совпадает"}
                )
        return await call_next(request)

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
