"""Короткоживущие билеты комнаты и real-time события проекта."""

import asyncio
import json
import math
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.websockets import WebSocketState

from app.api.access import ProjectRole, ensure_project_access, get_active_share_link
from app.api.auth import OptionalUserDep
from app.api.deps import ContainerDep
from app.api.schemas.common import ApiModel, errors
from app.services.collaboration import Participant, RealtimeHub, RoomFullError, Ticket
from app.services.errors import NotFoundError, UnauthorizedError

router = APIRouter(tags=["collaboration"])
MAX_MESSAGE_BYTES = 8 * 1024
MAX_SELECTION = 20
MAX_COORDINATE = 1_000_000
MAX_ELEMENT_ID_LENGTH = 255
MAX_DRAG_ELEMENTS = 20
PRESENCE_INTERVAL_SEC = 0.05
ACCESS_RECHECK_SEC = 30
WS_SUBPROTOCOL = "bpmn.collaboration.v1"
WS_TICKET_PREFIX = "bpmn.ticket."


class CollaborationTicket(ApiModel):
    ticket: str
    expires_at: datetime


class CursorPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: float
    y: float

    @field_validator("x", "y")
    @classmethod
    def finite_coordinates(cls, value: float) -> float:
        if not math.isfinite(value) or abs(value) > MAX_COORDINATE:
            raise ValueError("Некорректная позиция указателя")
        return value


class DiagramDrag(BaseModel):
    model_config = ConfigDict(extra="forbid")
    element_ids: list[str] = Field(min_length=1, max_length=MAX_DRAG_ELEMENTS)
    start: CursorPoint
    current: CursorPoint
    phase: Literal["moving", "released"] = "moving"

    @field_validator("element_ids")
    @classmethod
    def valid_drag_ids(cls, values: list[str]) -> list[str]:
        if any(not value or len(value) > MAX_ELEMENT_ID_LENGTH for value in values):
            raise ValueError("Некорректный id элемента")
        return list(dict.fromkeys(values))


class PresenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["presence.update"]
    protocol_version: Literal[1]
    cursor: CursorPoint | None = None
    selection: list[str] = Field(default_factory=list, max_length=MAX_SELECTION)
    activity: Literal["idle", "editing"] = "idle"
    drag: DiagramDrag | None = None

    @field_validator("selection")
    @classmethod
    def valid_element_ids(cls, values: list[str]) -> list[str]:
        if any(not value or len(value) > MAX_ELEMENT_ID_LENGTH for value in values):
            raise ValueError("Некорректный id элемента")
        return list(dict.fromkeys(values))


class Ping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["ping"]
    protocol_version: Literal[1]
    sent_at: int | None = None


@router.post(
    "/projects/{project_id}/collaboration-ticket",
    response_model=CollaborationTicket,
    responses=errors(401, 403, 404, 422, 429),
)
async def issue_project_ticket(
    project_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> CollaborationTicket:
    role = await ensure_project_access(request, container, project_id, user, write=False)
    if user is None and request.app.state.auth_enabled:
        raise UnauthorizedError("Войдите в аккаунт")
    display_name = user.email if user else "Локальный участник"
    ticket = container.realtime.issue_ticket(
        project_id=project_id,
        role=role,
        user_id=user.id if user else None,
        display_name=display_name,
    )
    return CollaborationTicket(
        ticket=ticket, expires_at=datetime.now(UTC) + container.realtime.ticket_ttl
    )


@router.post(
    "/shares/{token}/collaboration-ticket",
    response_model=CollaborationTicket,
    responses=errors(401, 403, 404, 410, 422, 429),
)
async def issue_share_ticket(
    token: str,
    container: ContainerDep,
    user: OptionalUserDep,
) -> CollaborationTicket:
    link = await get_active_share_link(container, token)
    link_role = ProjectRole(link.role)
    if user is not None:
        membership_role = await container.access.project_role(link.project_id, user.id)
        if membership_role is None:
            if link_role is ProjectRole.EDITOR:
                raise UnauthorizedError("Войдите и примите приглашение редактора")
            # У вошедшего, но ещё не присоединившегося viewer-ссылкой пользователя нет
            # права читать обычные project routes; билет остаётся гостевым viewer.
            user_id = None
            display_name = "Гость по ссылке"
            role = ProjectRole.VIEWER
        else:
            user_id = user.id
            display_name = user.email
            role = membership_role
    else:
        if link_role is ProjectRole.EDITOR:
            raise UnauthorizedError("Для редактирования войдите и примите приглашение")
        user_id = None
        display_name = "Гость по ссылке"
        role = ProjectRole.VIEWER
    ticket = container.realtime.issue_ticket(
        project_id=link.project_id,
        role=role,
        user_id=user_id,
        display_name=display_name,
        share_link_id=link.id if user_id is None else None,
    )
    return CollaborationTicket(
        ticket=ticket, expires_at=datetime.now(UTC) + container.realtime.ticket_ttl
    )


@router.websocket("/projects/{project_id}/collaboration/ws")
async def project_collaboration_socket(websocket: WebSocket, project_id: UUID) -> None:
    container = websocket.app.state.container
    hub: RealtimeHub = container.realtime
    if not _origin_allowed(websocket):
        await websocket.close(code=1008, reason="Недопустимый источник подключения")
        return
    ticket = _ticket_from_subprotocol(websocket.headers.get("sec-websocket-protocol", ""))
    principal = hub.consume_ticket(ticket, project_id=project_id) if ticket else None
    if principal is None or not await _ticket_is_current(container, principal):
        await websocket.close(code=1008, reason="Ссылка на подключение истекла")
        return

    latest = await container.versions.list(project_id)
    head = latest[0] if latest else None
    active = await container.repos.runs.active_for_project(project_id)
    try:
        participant = await hub.join(project_id, principal)
    except RoomFullError:
        await websocket.close(code=1013, reason="В комнате слишком много участников")
        return
    try:
        await websocket.accept(subprotocol=WS_SUBPROTOCOL)
        await websocket.send_json(
            {
                "type": "ready",
                "protocol_version": 1,
                "project_id": str(project_id),
                "session_id": str(participant.session_id),
                "role": participant.role.value,
                "head_version_id": str(head.id) if head else None,
                "head_version_number": head.number if head else None,
                "head_revision": head.number if head else 0,
                "participants": await hub.snapshot(project_id),
                "active_run": _run_message(active) if active else None,
            }
        )
        await _serve_connection(websocket, container, participant)
    finally:
        await hub.leave(participant)


def _ticket_from_subprotocol(header: str) -> str | None:
    for protocol in header.split(","):
        candidate = protocol.strip()
        if candidate.startswith(WS_TICKET_PREFIX):
            ticket = candidate.removeprefix(WS_TICKET_PREFIX)
            return ticket or None
    return None


def _origin_allowed(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin")
    if not origin:
        return True  # clients other than browsers may omit Origin; they still need a ticket.
    settings = websocket.app.state.container.settings
    configured = {item.rstrip("/") for item in settings.cors_origins}
    if origin.rstrip("/") in configured:
        return True
    # Same-origin deployments may not list their public hostname in CORS because the frontend
    # and API share a host. Respect proxy headers only from the configured reverse-proxy path.
    host = websocket.headers.get("host")
    parsed_origin = urlsplit(origin)
    return bool(
        host
        and parsed_origin.scheme in {"http", "https"}
        and parsed_origin.netloc.casefold() == host.casefold()
        and parsed_origin.path in {"", "/"}
        and not parsed_origin.query
        and not parsed_origin.fragment
    )


async def _ticket_is_current(container, ticket: Ticket) -> bool:
    if ticket.user_id is not None:
        role = await container.access.project_role(ticket.project_id, ticket.user_id)
        return role is ticket.role
    if ticket.share_link_id is not None:
        try:
            link = await container.access.active_link_by_id(ticket.share_link_id)
        except NotFoundError:
            return False
        return link.project_id == ticket.project_id and link.role == ProjectRole.VIEWER.value
    return not container.settings.auth_enabled


async def _serve_connection(websocket: WebSocket, container, participant: Participant) -> None:
    hub: RealtimeHub = container.realtime
    sender = asyncio.create_task(_send_events(websocket, participant))
    receiver = asyncio.create_task(_receive_events(websocket, hub, participant))
    try:
        while websocket.application_state is WebSocketState.CONNECTED:
            done, _ = await asyncio.wait(
                {sender, receiver}, timeout=ACCESS_RECHECK_SEC, return_when=asyncio.FIRST_COMPLETED
            )
            if done:
                for task in done:
                    task.result()
                break
            if not await _ticket_is_current(
                container,
                Ticket(
                    project_id=participant.project_id,
                    role=participant.role,
                    user_id=participant.user_id,
                    display_name=participant.display_name,
                    share_link_id=participant.share_link_id,
                    expires_at=datetime.max.replace(tzinfo=UTC),
                ),
            ):
                await websocket.close(code=1008, reason="Доступ к проекту изменён")
                break
    except WebSocketDisconnect:
        pass
    finally:
        sender.cancel()
        receiver.cancel()
        await asyncio.gather(sender, receiver, return_exceptions=True)


async def _send_events(websocket: WebSocket, participant: Participant) -> None:
    while websocket.application_state is WebSocketState.CONNECTED:
        event = await participant.queue.get()
        await websocket.send_json(event)


async def _receive_events(websocket: WebSocket, hub: RealtimeHub, participant: Participant) -> None:
    last_presence = 0.0
    while websocket.application_state is WebSocketState.CONNECTED:
        try:
            raw = await websocket.receive_text()
        except RuntimeError:
            await websocket.close(code=1003, reason="Ожидаются текстовые JSON-сообщения")
            return
        if len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
            await websocket.send_json(
                {
                    "type": "error",
                    "code": "invalid_message",
                    "message": "Сообщение слишком большое",
                }
            )
            continue
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("Ожидается JSON-объект")
            if data.get("type") == "ping":
                Ping.model_validate(data)
                await websocket.send_json({"type": "pong", "sent_at": data.get("sent_at")})
                continue
            message = PresenceUpdate.model_validate(data)
        except (json.JSONDecodeError, ValidationError, ValueError):
            await websocket.send_json(
                {
                    "type": "error",
                    "code": "invalid_message",
                    "message": "Некорректный формат сообщения",
                }
            )
            continue
        now = asyncio.get_running_loop().time()
        if now - last_presence < PRESENCE_INTERVAL_SEC:
            await websocket.send_json(
                {
                    "type": "error",
                    "code": "rate_limited",
                    "message": "Слишком частые обновления указателя",
                }
            )
            continue
        last_presence = now
        cursor = message.cursor.model_dump() if message.cursor else None
        await hub.update_presence(
            participant,
            cursor=cursor,
            selection=message.selection,
            activity=message.activity if participant.role is not ProjectRole.VIEWER else "idle",
            drag=(
                message.drag.model_dump()
                if message.drag is not None and participant.role is not ProjectRole.VIEWER
                else None
            ),
        )


def _run_message(run) -> dict[str, object]:
    return {
        "type": "run.changed",
        "run_id": str(run.id),
        "mode": run.mode.value,
        "status": run.status.value,
        "actor": run.actor_email,
        "stage": run.stage.value if run.stage else None,
        "progress": run.progress,
        "version_id": str(run.version_id) if run.version_id else None,
        "error": run.error,
    }


__all__ = ["router"]
