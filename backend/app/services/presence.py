"""Краткоживущее присутствие на доске; в БД не записывается."""

import asyncio
from dataclasses import dataclass
from uuid import UUID, uuid4

from app.domain.access import ProjectRole


@dataclass(frozen=True, slots=True)
class PresentUser:
    id: UUID
    email: str
    role: ProjectRole


class PresenceRegistry:
    """Одна запись на человека при любом числе открытых вкладок."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._connections: dict[
            UUID, dict[UUID, tuple[PresentUser, asyncio.Queue[list[PresentUser]]]]
        ] = {}

    def _snapshot(self, project_id: UUID) -> list[PresentUser]:
        users = {entry.id: entry for entry, _ in self._connections.get(project_id, {}).values()}
        return sorted(users.values(), key=lambda user: (user.email, str(user.id)))

    def _broadcast(self, project_id: UUID) -> None:
        snapshot = self._snapshot(project_id)
        for _, queue in self._connections.get(project_id, {}).values():
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(snapshot)

    async def join(
        self, project_id: UUID, user: PresentUser
    ) -> tuple[UUID, asyncio.Queue[list[PresentUser]]]:
        connection_id = uuid4()
        queue: asyncio.Queue[list[PresentUser]] = asyncio.Queue(maxsize=1)
        async with self._lock:
            self._connections.setdefault(project_id, {})[connection_id] = (user, queue)
            self._broadcast(project_id)
        return connection_id, queue

    async def leave(self, project_id: UUID, connection_id: UUID) -> None:
        async with self._lock:
            connections = self._connections.get(project_id)
            if connections is None:
                return
            connections.pop(connection_id, None)
            if connections:
                self._broadcast(project_id)
            else:
                self._connections.pop(project_id, None)
