"""Фоновые задачи процесса: прогоны и разбор документов (RFC §5.1 — asyncio, без очереди).

При старте `Database.initialize()` переводит незавершённые прогоны в `failed`, при остановке
активные задачи отменяются; `RunService` сохраняет итоговый статус перед завершением.
"""

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class TaskSpawner(Protocol):
    def spawn(self, coro: Coroutine[Any, Any, None], *, name: str) -> None: ...
    async def cancel(self, *, name: str) -> bool: ...
    async def shutdown(self) -> None: ...


class AsyncioTaskSpawner:
    """Держит ссылки на задачи (иначе их может собрать GC) и отменяет их при остановке."""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[None]] = set()

    def spawn(self, coro: Coroutine[Any, Any, None], *, name: str) -> None:
        task = asyncio.get_running_loop().create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._finished)

    def _finished(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error("Фоновая задача %s упала", task.get_name(), exc_info=task.exception())

    async def cancel(self, *, name: str) -> bool:
        """Отменить задачу по стабильному имени и дождаться её безопасного завершения."""
        task = next((item for item in self._tasks if item.get_name() == name), None)
        if task is None:
            return False
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return True

    async def shutdown(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def wait_idle(self) -> None:
        """Дождаться всех текущих задач (для тестов и плавной остановки)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
