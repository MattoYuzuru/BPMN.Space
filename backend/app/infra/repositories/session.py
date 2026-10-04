"""Источник сессий SQLAlchemy: по сессии на операцию или одна на транзакцию."""

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class BoundSessions:
    """Одна сессия на всю транзакцию `Repositories.atomic()`.

    Выдаёт её вместо новой и сам ничего не фиксирует: коммит или откат делает внешний
    `sessions.begin()`. Операции записи сбрасываются (`flush`) сразу, чтобы нарушение
    ограничения БД (например, активный прогон) всплывало в месте вызова.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def __call__(self) -> AbstractAsyncContextManager[AsyncSession]:
        return self._scope(flush=False)

    def begin(self) -> AbstractAsyncContextManager[AsyncSession]:
        return self._scope(flush=True)

    @asynccontextmanager
    async def _scope(self, *, flush: bool) -> AsyncIterator[AsyncSession]:
        yield self._session
        if flush:
            await self._session.flush()


type SessionFactory = async_sessionmaker[AsyncSession] | BoundSessions
