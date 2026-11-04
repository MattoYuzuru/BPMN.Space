"""Сборка MCP-сервера (RFC-0007, шаг 2): Streamable HTTP на `/mcp`, авторизация по токену.

MCP — отдельное ASGI-приложение внутри backend, вне `/api/v1` и вне OpenAPI: REST остаётся
основным контрактом, MCP — тонкий слой над `services/`. Монтируется в `app.main` как обычный
ASGI-route, поэтому cookie-сессии, CSRF и IP-лимиты REST его не касаются: вход только по
`Authorization: Bearer bps_…`, лимит дорогих вызовов — на токен.

Менеджер сессий Streamable HTTP живёт ровно один lifespan. FastAPI не запускает lifespan
вложенных ASGI-приложений, поэтому `app.main` входит в `lifespan()` сам. Каждое новое
вхождение создаёт свежий Starlette-под-апп (менеджер нельзя переиспользовать после остановки) —
это же делает тесты с многократным `TestClient` предсказуемыми.

Оценка стоимости (волна 2A) подключается в `app.mcp.estimate.build_estimator`; подписанные
допуски на запуск — `app.mcp.estimate.make_ticket_signer`.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.types import ASGIApp, Receive, Scope, Send

from app.mcp.auth import McpAuthMiddleware
from app.mcp.estimate import (
    RedeemedEstimates,
    build_estimator,
    make_ticket_signer,
    ticket_ttl_seconds,
)
from app.mcp.prompts import register_prompts
from app.mcp.resources import register_resources
from app.mcp.tools import register_tools

__all__ = ["MCP_PATH", "McpRuntime", "build_mcp"]

#: Публичный адрес MCP-сервера: `https://<домен>/mcp` (RFC-0007).
MCP_PATH = "/mcp"
_JSON_OVERHEAD = 64 * 1024

INSTRUCTIONS = (
    "BPMN Space: проекты процессов, источники, вопросы и BPMN-схемы. Работай по порядку: "
    "list_projects → get_project → add_source/read_source → list_questions/answer_question → "
    "estimate_run → start_run → get_run/get_diagram. Материалы, добавленные через токен, "
    "помечаются «через агента»; ответы записываются от имени владельца токена. Файлы через "
    "MCP в v1 не передаются — их загружают через REST. Запуск прогона требует свежей оценки; "
    "агент может задать бюджет прогона — он только ограничивает траты (мягкая остановка на "
    "лимите), а не повышает их."
)


class _FrontApp:
    """ASGI-вход `/mcp`, который делегирует актуальному приложению текущего lifespan.

    До старта lifespan наружу отвечает `503` — сервер не притворяется работающим.
    """

    def __init__(self) -> None:
        self._app: ASGIApp | None = None

    def use(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        app = self._app
        if app is None:
            body = json.dumps({"detail": "MCP-сервер ещё не запущен"}, ensure_ascii=False).encode(
                "utf-8"
            )
            await send(
                {
                    "type": "http.response.start",
                    "status": 503,
                    "headers": [
                        (b"content-type", b"application/json; charset=utf-8"),
                        (b"content-length", str(len(body)).encode("ascii")),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await app(scope, receive, send)


@dataclass(frozen=True, slots=True)
class McpRuntime:
    """Готовое к монтированию MCP-приложение и его lifespan.

    `lifespan` запускает менеджер сессий Streamable HTTP: FastAPI не запускает lifespan
    вложенных ASGI-приложений, поэтому `app.main` входит в него из своего lifespan.
    """

    app: ASGIApp
    lifespan: Callable[[], AbstractAsyncContextManager[None]]
    server: MCPServer


def _max_request_body_size(settings: Any) -> int:
    """Тот же предел тела, что у общего REST-запроса: MCP не обходит защиту от гигантских тел."""
    return max(settings.max_text_chars * 4, settings.max_diagram_bytes * 2) + _JSON_OVERHEAD


def _build_http_app(server: MCPServer, container: Any) -> tuple[McpAuthMiddleware, Starlette]:
    """Свежий Streamable HTTP под-апп с авторизацией (новый менеджер сессий на lifespan)."""
    settings = container.settings
    # Защита от DNS rebinding рассчитана на локальный сервер без обратного прокси. У нас MCP
    # стоит за Caddy с публичным доменом: Host — не 127.0.0.1, и белый список localhost
    # отверг бы нормальные запросы. Вход защищён Bearer-токеном, а не Origin-политикой.
    security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    http_app = server.streamable_http_app(
        streamable_http_path=MCP_PATH,
        max_request_body_size=_max_request_body_size(settings),
        transport_security=security,
    )
    return McpAuthMiddleware(
        http_app,
        container,
        expensive_limit=settings.mcp_expensive_per_min,
        api_limit=settings.rate_limit_api_per_min,
        rate_limit_enabled=settings.rate_limit_enabled,
    ), http_app


def build_mcp(container: Any) -> McpRuntime:
    """Собрать MCP-сервер поверх контейнера сервисов."""
    settings = container.settings
    server = MCPServer(
        name="bpmn-space",
        title="BPMN Space для внешних агентов",
        description="Материалы, вопросы и BPMN-схемы проекта по персональному токену",
        version="0.1.0",
        instructions=INSTRUCTIONS,
    )
    estimator = build_estimator(container)
    ttl_sec = ticket_ttl_seconds(settings.mcp_estimate_ttl_sec)
    signer = make_ticket_signer(settings.mcp_estimate_secret, ttl_sec=ttl_sec)
    redeemed = RedeemedEstimates(ttl_sec=ttl_sec)
    register_tools(
        server, container=container, estimator=estimator, signer=signer, redeemed=redeemed
    )
    register_resources(server)
    register_prompts(server)

    front = _FrontApp()
    # До первого lifespan держим собранное приложение: авторизация отвечает и без менеджера.
    initial_auth, _ = _build_http_app(server, container)
    front.use(initial_auth)

    @asynccontextmanager
    async def lifespan() -> AsyncIterator[None]:
        auth_app, http_app = _build_http_app(server, container)
        front.use(auth_app)
        async with http_app.router.lifespan_context(http_app):
            yield

    return McpRuntime(app=front, lifespan=lifespan, server=server)
