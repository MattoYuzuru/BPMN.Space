"""Шина событий прогонов для SSE: журнал событий на прогон + подписка с досылкой истории.

Подписчик, пришедший позже, сначала получает всю историю (или хвост после `Last-Event-ID`),
затем новые события; поток заканчивается после события `done`.
Реализация in-process: backend один (RFC §6 — без Redis). Журнал хранится для последних
`max_runs` прогонов.
После рестарта журнал пуст: для завершённых прогонов API синтезирует `done` из строки БД,
а незавершённые при старте помечаются `failed` (RFC §5.1).
"""

import asyncio
import copy
from collections import OrderedDict
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from app.domain.runs import RunEvent, RunEventKind, RunEventPayload


class RunEventBus(Protocol):
    async def publish(self, run_id: UUID, kind: RunEventKind, payload: RunEventPayload) -> None:
        """Добавляет событие в журнал прогона; `done` закрывает журнал."""
        ...

    def has_log(self, run_id: UUID) -> bool: ...

    def subscribe(self, run_id: UUID, *, after: int = 0) -> AsyncIterator[RunEvent]:
        """События с `id > after`: сначала история, затем новые до `done` включительно."""
        ...


@dataclass(slots=True)
class _RunLog:
    events: list[RunEvent] = field(default_factory=list[RunEvent])
    closed: bool = False
    changed: asyncio.Event = field(default_factory=asyncio.Event)


class InMemoryRunEventBus:
    def __init__(self, *, max_runs: int = 500) -> None:
        self._logs: OrderedDict[UUID, _RunLog] = OrderedDict()
        self._max_runs = max_runs

    def _log(self, run_id: UUID) -> _RunLog:
        log = self._logs.get(run_id)
        if log is None:
            log = self._logs[run_id] = _RunLog()
            while len(self._logs) > self._max_runs:
                self._logs.popitem(last=False)
        return log

    def has_log(self, run_id: UUID) -> bool:
        return run_id in self._logs

    async def publish(self, run_id: UUID, kind: RunEventKind, payload: RunEventPayload) -> None:
        log = self._log(run_id)
        if log.closed:
            return
        event = RunEvent(id=len(log.events) + 1, kind=kind, payload=copy.deepcopy(payload))
        log.events.append(event)
        if kind is RunEventKind.DONE:
            log.closed = True
        log.changed.set()
        log.changed = asyncio.Event()

    async def subscribe(self, run_id: UUID, *, after: int = 0) -> AsyncIterator[RunEvent]:
        log = self._log(run_id)
        position = max(after, 0)
        while True:
            while position < len(log.events):
                yield log.events[position]
                position += 1
            if log.closed:
                return
            await log.changed.wait()
