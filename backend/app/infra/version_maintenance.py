"""Пакетное сжатие старых версий или подготовка к откату старого приложения.

Запуск: python -m app.infra.version_maintenance
[--restore | --materialize-metadata] [--batch-size 100].
DATABASE_URL берётся из штатных Settings. Скрипт не запускает сид и не меняет прогоны.
"""

import argparse
import asyncio

from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.infra.db_models import DiagramVersionRow
from app.infra.repositories.sql import SqlVersionRepository
from app.infra.version_codec import MAX_MAINTENANCE_BATCH


async def maintain(*, restore: bool, batch_size: int, materialize: bool = False) -> int:
    settings = Settings()
    if not settings.database_url:
        raise ValueError("Для обслуживания версий нужен DATABASE_URL")
    engine = create_async_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = SqlVersionRepository(sessions)
    total = 0
    inherits = False
    try:
        if restore or materialize:
            async with engine.connect() as connection:
                columns = await connection.run_sync(
                    lambda sync: {
                        column["name"] for column in inspect(sync).get_columns("diagram_versions")
                    }
                )
            # Сбой до применения миграции: для возврата старого релиза делать нечего.
            if restore and "packed_xml" not in columns:
                print("Компактная схема ещё не установлена; восстановление не требуется.")
                return 0
            inherits = "trace_inherited" in columns
            if materialize and not inherits:
                print("Унаследованных метаданных ещё нет; материализация не требуется.")
                return 0
        async with sessions() as session:
            projects = list(await session.scalars(select(DiagramVersionRow.project_id).distinct()))
        for project_id in projects:
            # Старый код не знает про унаследованные цитаты/отчёт: вернуть их в строки.
            while (
                (restore or materialize)
                and inherits
                and await repository.materialize_inherited_batch(project_id, limit=batch_size)
            ):
                pass
            while not materialize and (
                count := await repository.maintain_batch(
                    project_id, restore=restore, limit=batch_size
                )
            ):
                total += count
                print(f"Обработано версий: {total}", flush=True)
        return total
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--restore", action="store_true")
    # Откат на релиз до сессий правок (ADR-0010): XML остаётся сжатым, метаданные — в строках.
    modes.add_argument("--materialize-metadata", action="store_true")
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= MAX_MAINTENANCE_BATCH:
        parser.error("--batch-size: от 1 до 1000")
    asyncio.run(
        maintain(
            restore=args.restore,
            batch_size=args.batch_size,
            materialize=args.materialize_metadata,
        )
    )


if __name__ == "__main__":
    main()
