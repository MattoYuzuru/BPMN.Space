"""MCP-сервер внешних агентов (RFC-0007, шаг 2): `/mcp` поверх `services/`.

Пакет — слой представления, как `app.api`: ходит только в `app.services` и `app.domain`
(плюс `mcp` SDK), не импортирует `app.infra` и не знает о SQL. Вход — персональный токен
доступа `Authorization: Bearer bps_…`; права инструментов — закрытая таблица в `app.mcp.auth`.
"""

from app.mcp.server import MCP_PATH, McpRuntime, build_mcp

__all__ = ["MCP_PATH", "McpRuntime", "build_mcp"]
