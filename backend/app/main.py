"""Точка входа FastAPI."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from pydantic.json_schema import models_json_schema

from app.api.errors import install_error_handlers
from app.api.v1 import api_router
from app.api.v1.runs import OPENAPI_EXTRA_MODELS
from app.config import Settings, get_settings
from app.container import Container, build_container


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

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await container.spawner.shutdown()

    app = FastAPI(
        title="Архитектор BPMN-диаграмм",
        version="0.1.0",
        lifespan=lifespan,
        generate_unique_id_function=lambda route: route.name,
    )
    app.state.container = container
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_error_handlers(app)
    app.include_router(api_router, prefix=settings.api_prefix)

    @app.get("/health", tags=["service"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.openapi = lambda: _openapi(app)  # type: ignore[method-assign]
    return app


app = create_app()
