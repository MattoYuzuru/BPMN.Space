"""Ограниченная параллельность независимых задач с детерминированным порядком результатов."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence


async def bounded_gather[T](
    factories: Sequence[Callable[[], Awaitable[T]]], *, limit: int
) -> list[T]:
    """Запускает фабрики корутин не более чем по `limit` одновременно.

    Результаты возвращаются в порядке `factories`, а не завершения, поэтому следующая за вызовом
    обработка не зависит от скорости ответов. При первой ошибке остальные задачи отменяются и
    ждутся, а ошибка пробрасывается как есть (не `ExceptionGroup`). Отмена вызывающего
    отменяет все дочерние задачи. `limit <= 1` — строго последовательное выполнение без задач.
    """
    if limit <= 1 or len(factories) <= 1:
        return [await factory() for factory in factories]
    semaphore = asyncio.Semaphore(limit)

    async def run(factory: Callable[[], Awaitable[T]]) -> T:
        async with semaphore:
            return await factory()

    tasks = [asyncio.ensure_future(run(factory)) for factory in factories]
    try:
        return list(await asyncio.gather(*tasks))
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


def adaptive_deadline(
    base_sec: float, *, total_chars: int, per_1k_chars_sec: float, max_sec: float
) -> float | None:
    """Срок прогона: `base_sec` плюс время на объём текста, не выше `max_sec` (но не ниже базы).

    `base_sec <= 0` — срока нет (`None`); `max_sec <= 0` — потолка нет.
    """
    if base_sec <= 0:
        return None
    extended = base_sec + per_1k_chars_sec * max(total_chars, 0) / 1000
    if max_sec > 0:
        extended = min(extended, max(max_sec, base_sec))
    return extended
