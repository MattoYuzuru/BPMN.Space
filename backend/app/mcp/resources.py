"""Ресурсы MCP (RFC-0007): `project://{id}/diagram.bpmn` и `project://{id}/questions`.

Ресурс — адресуемое чтение без побочных эффектов: тот же доступ, что у инструментов
(`projects:read`, проект токена, роль не ниже viewer), и никаких ключей или внутренних полей.
Схема отдаётся как `application/xml`, вопросы — как JSON.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context
from mcp.server.mcpserver.exceptions import ResourceNotFoundError

from app.mcp.auth import (
    as_tool_error,
    begin_operation,
    ensure_project,
    resource_policy,
    review_scope,
)
from app.mcp.diagram import latest_version
from app.mcp.serializers import question_view, uuid_or_404
from app.services.errors import NotFoundError, ServiceError

__all__ = ["register_resources"]


def register_resources(server: MCPServer) -> None:
    """Зарегистрировать ресурсы проекта. Права — в `app.mcp.auth.RESOURCE_POLICIES`."""

    @server.resource(
        "project://{project_id}/diagram.bpmn",
        name="project_diagram",
        title="Схема BPMN проекта",
        description=(
            "BPMN 2.0 XML последней версии схемы проекта. Требуется право projects:read и "
            "доступ к проекту (владелец, редактор, наблюдатель или демо-проект)."
        ),
        mime_type="application/xml",
    )
    async def project_diagram(
        project_id: str,
        ctx: Context,
    ) -> str:
        identity = begin_operation(ctx, resource_policy("project_diagram"))
        pid = uuid_or_404(project_id, "project_id")
        try:
            await ensure_project(identity, pid, write=False)
            version = await latest_version(identity.container, pid)
        except NotFoundError as error:
            raise ResourceNotFoundError(error.message) from None
        except ServiceError as error:
            raise as_tool_error(error) from None
        return version.xml

    @server.resource(
        "project://{project_id}/questions",
        name="project_questions",
        title="Вопросы проекта",
        description=(
            "Вопросы проекта с ответами и провенансом «через агента» в виде JSON. "
            "Требуется право projects:read и доступ к проекту."
        ),
        mime_type="application/json",
    )
    async def project_questions(
        project_id: str,
        ctx: Context,
    ) -> str:
        identity = begin_operation(ctx, resource_policy("project_questions"))
        pid = uuid_or_404(project_id, "project_id")
        try:
            await ensure_project(identity, pid, write=False)
            questions = await identity.container.questions.list(pid, status=None)
            scope = review_scope(identity)
            if scope is not None:
                questions = await identity.container.review.filter_questions(pid, questions, scope)
        except NotFoundError as error:
            raise ResourceNotFoundError(error.message) from None
        except ServiceError as error:
            raise as_tool_error(error) from None
        payload: list[dict[str, Any]] = [question_view(question) for question in questions]
        return json.dumps(payload, ensure_ascii=False, indent=2)
