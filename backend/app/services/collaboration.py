"""Краткоживущие WebSocket-комнаты и одноразовые билеты совместной работы."""

import asyncio
import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.domain.access import ProjectRole

TICKET_TTL = timedelta(seconds=60)
ROOM_QUEUE_SIZE = 128
CURSOR_PALETTE_SIZE = 8
MAX_ROOM_PARTICIPANTS = 20
MAX_USER_CONNECTIONS = 3
RELEASED_DRAG_TTL_SEC = 20


class RoomFullError(Exception):
    """Комната или пользователь уже достигли предела соединений."""


@dataclass(frozen=True, slots=True)
class Ticket:
    project_id: UUID
    role: ProjectRole
    user_id: UUID | None
    display_name: str
    share_link_id: UUID | None
    expires_at: datetime


@dataclass(slots=True)
class Participant:
    connection_id: UUID
    session_id: UUID
    project_id: UUID
    role: ProjectRole
    user_id: UUID | None
    display_name: str
    color_key: int
    queue: asyncio.Queue[dict[str, object]]
    share_link_id: UUID | None = None
    cursor: dict[str, float] | None = None
    selection: list[str] = field(default_factory=list)
    activity: str = "idle"
    drag: dict[str, object] | None = None
    drag_updated_at: float = 0.0

    def public(self) -> dict[str, object]:
        return {
            "session_id": str(self.session_id),
            "user_id": str(self.user_id) if self.user_id else None,
            "display_name": self.display_name,
            "role": self.role.value,
            "color_key": self.color_key,
            "cursor": self.cursor,
            "selection": self.selection,
            "activity": self.activity,
            "drag": self.drag,
        }


class RealtimeHub:
    """Одна worker-процессная шина для ephemeral событий; постоянные данные остаются в Postgres."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._tickets: dict[str, Ticket] = {}
        self._rooms: dict[UUID, dict[UUID, Participant]] = {}

    @property
    def ticket_ttl(self) -> timedelta:
        return TICKET_TTL

    def issue_ticket(
        self,
        *,
        project_id: UUID,
        role: ProjectRole,
        user_id: UUID | None,
        display_name: str,
        share_link_id: UUID | None = None,
        now: datetime | None = None,
    ) -> str:
        now = now or datetime.now(UTC)
        raw = secrets.token_urlsafe(32)
        digest = hashlib.sha256(raw.encode()).hexdigest()
        self._purge_tickets(now)
        self._tickets[digest] = Ticket(
            project_id=project_id,
            role=role,
            user_id=user_id,
            display_name=display_name,
            share_link_id=share_link_id,
            expires_at=now + TICKET_TTL,
        )
        return raw

    def consume_ticket(
        self, raw: str, *, project_id: UUID, now: datetime | None = None
    ) -> Ticket | None:
        now = now or datetime.now(UTC)
        digest = hashlib.sha256(raw.encode()).hexdigest()
        ticket = self._tickets.pop(digest, None)
        if ticket is None or ticket.project_id != project_id or ticket.expires_at <= now:
            return None
        return ticket

    def _purge_tickets(self, now: datetime) -> None:
        self._tickets = {
            digest: ticket for digest, ticket in self._tickets.items() if ticket.expires_at > now
        }

    async def join(self, project_id: UUID, ticket: Ticket) -> Participant:
        connection_id = uuid4()
        participant = Participant(
            connection_id=connection_id,
            session_id=uuid4(),
            project_id=project_id,
            role=ticket.role,
            user_id=ticket.user_id,
            display_name=ticket.display_name,
            color_key=int.from_bytes(
                hashlib.sha256(str(ticket.user_id or connection_id).encode()).digest()[:2], "big"
            )
            % CURSOR_PALETTE_SIZE,
            queue=asyncio.Queue(maxsize=ROOM_QUEUE_SIZE),
            share_link_id=ticket.share_link_id,
        )
        async with self._lock:
            room = self._rooms.setdefault(project_id, {})
            if len(room) >= MAX_ROOM_PARTICIPANTS:
                if not room:
                    self._rooms.pop(project_id, None)
                raise RoomFullError("В проекте уже максимальное число участников")
            if ticket.user_id is not None:
                user_connections = sum(item.user_id == ticket.user_id for item in room.values())
                if user_connections >= MAX_USER_CONNECTIONS:
                    raise RoomFullError("Открыто максимальное число вкладок проекта")
            room[connection_id] = participant
            self._broadcast_locked(
                project_id,
                {
                    "type": "presence.snapshot",
                    "participants": self._snapshot_locked(project_id),
                },
            )
        return participant

    async def snapshot(self, project_id: UUID) -> list[dict[str, object]]:
        async with self._lock:
            self._expire_released_drags_locked(project_id)
            return self._snapshot_locked(project_id)

    async def leave(self, participant: Participant) -> None:
        async with self._lock:
            room = self._rooms.get(participant.project_id)
            if room is None:
                return
            room.pop(participant.connection_id, None)
            if room:
                self._broadcast_locked(
                    participant.project_id,
                    {
                        "type": "presence.snapshot",
                        "participants": self._snapshot_locked(participant.project_id),
                    },
                )
            else:
                self._rooms.pop(participant.project_id, None)

    async def update_presence(
        self,
        participant: Participant,
        *,
        cursor: dict[str, float] | None,
        selection: list[str],
        activity: str,
        drag: dict[str, object] | None,
    ) -> None:
        async with self._lock:
            current = self._rooms.get(participant.project_id, {}).get(participant.connection_id)
            if current is None:
                return
            current.cursor = cursor
            current.selection = selection
            current.activity = activity
            now = asyncio.get_running_loop().time()
            keep_released = (
                drag is None
                and current.drag is not None
                and current.drag.get("phase") == "released"
                and now - current.drag_updated_at < RELEASED_DRAG_TTL_SEC
            )
            if not keep_released:
                current.drag = drag
                current.drag_updated_at = now
            self._broadcast_locked(
                participant.project_id,
                {"type": "presence.changed", "participant": current.public()},
            )

    async def publish(self, project_id: UUID, event: dict[str, object]) -> None:
        async with self._lock:
            self._expire_released_drags_locked(project_id)
            is_saved_version = event.get("type") == "diagram.version" or (
                event.get("type") == "run.changed" and event.get("version_id") is not None
            )
            if is_saved_version:
                for participant in self._rooms.get(project_id, {}).values():
                    participant.drag = None
                    participant.drag_updated_at = 0.0
                self._broadcast_locked(
                    project_id,
                    {
                        "type": "presence.snapshot",
                        "participants": self._snapshot_locked(project_id),
                    },
                )
            self._broadcast_locked(project_id, event)

    def _expire_released_drags_locked(self, project_id: UUID) -> None:
        now = asyncio.get_running_loop().time()
        changed = False
        for participant in self._rooms.get(project_id, {}).values():
            if (
                participant.drag is not None
                and participant.drag.get("phase") == "released"
                and now - participant.drag_updated_at >= RELEASED_DRAG_TTL_SEC
            ):
                participant.drag = None
                participant.drag_updated_at = 0.0
                changed = True
        if changed:
            self._broadcast_locked(
                project_id,
                {
                    "type": "presence.snapshot",
                    "participants": self._snapshot_locked(project_id),
                },
            )

    def _snapshot_locked(self, project_id: UUID) -> list[dict[str, object]]:
        # Remove a stale drop preview before exposing room state to a newly joined tab.
        now = asyncio.get_running_loop().time()
        for participant in self._rooms.get(project_id, {}).values():
            if (
                participant.drag is not None
                and participant.drag.get("phase") == "released"
                and now - participant.drag_updated_at >= RELEASED_DRAG_TTL_SEC
            ):
                participant.drag = None
                participant.drag_updated_at = 0.0
        return [item.public() for item in self._rooms.get(project_id, {}).values()]

    def _broadcast_locked(self, project_id: UUID, event: dict[str, object]) -> None:
        for participant in self._rooms.get(project_id, {}).values():
            if participant.queue.full():
                # Presence is ephemeral; if the queue is saturated, discard stale frames and ask
                # the client to reload durable project state rather than silently miss a version.
                while not participant.queue.empty():
                    participant.queue.get_nowait()
                participant.queue.put_nowait(
                    {"type": "resync.required", "reason": "live_queue_overflow"}
                )
                continue
            participant.queue.put_nowait(event)


__all__ = ["Participant", "RealtimeHub", "Ticket"]
