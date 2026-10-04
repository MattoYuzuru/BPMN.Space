"""SSE: кто сейчас открыл рабочее место проекта."""

import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sse_starlette import EventSourceResponse, ServerSentEvent

from app.api.access import ensure_project_access
from app.api.auth import OptionalUserDep
from app.api.deps import ContainerDep
from app.api.schemas.common import errors
from app.domain.access import ProjectRole
from app.services.errors import UnauthorizedError
from app.services.presence import PresentUser

router = APIRouter(tags=["presence"])


class PresenceUser(BaseModel):
    id: UUID
    email: str
    role: ProjectRole


class PresenceSnapshot(BaseModel):
    users: list[PresenceUser]


@router.get(
    "/projects/{project_id}/presence/events",
    response_class=EventSourceResponse,
    responses={
        200: {"description": "Снимки присутствия в SSE-событиях `presence`"},
        **errors(401, 404, 422),
    },
)
async def project_presence(
    project_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> EventSourceResponse:
    """Показывает только вошедших пользователей с доступом к проекту."""
    role = await ensure_project_access(request, container, project_id, user, write=False)
    if user is None:
        raise UnauthorizedError("Войдите в аккаунт")
    registry = request.app.state.presence

    async def stream() -> AsyncIterator[ServerSentEvent]:
        connection_id, queue = await registry.join(
            project_id, PresentUser(id=user.id, email=user.email, role=role)
        )
        try:
            while not await request.is_disconnected():
                try:
                    users = await asyncio.wait_for(queue.get(), timeout=30)
                except TimeoutError:
                    # При отзыве доступа закрываем поток даже без движения на доске.
                    await ensure_project_access(request, container, project_id, user, write=False)
                    continue
                yield ServerSentEvent(
                    event="presence",
                    data=PresenceSnapshot(
                        users=[PresenceUser.model_validate(u, from_attributes=True) for u in users]
                    ).model_dump_json(),
                )
        finally:
            await registry.leave(project_id, connection_id)

    return EventSourceResponse(stream(), ping=15)
