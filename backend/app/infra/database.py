"""Подключение к PostgreSQL: жизненный цикл, миграции и сид демо-данных."""

import logging
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.script.revision import ResolutionError
from alembic.util.exc import CommandError
from sqlalchemy import event, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.domain.models import RunStatus
from app.infra.db_models import Base, ProjectRow, RunRow
from app.infra.repositories.sql import SqlStore

logger = logging.getLogger(__name__)
SLOW_CHECKOUT_WARNING_SEC = 5.0
MAX_RUN_RECOVERIES = 2

INTERRUPTED_PARSE_ERROR = (
    "Разбор файла прервался из-за перезапуска сервера. "
    "Загрузите файл ещё раз или вставьте текст вручную"
)


def unknown_db_revisions(sync_connection: Any, config: Config) -> list[str]:
    """Ревизии БД, которых нет среди миграций этого релиза (схему применил более новый релиз)."""
    scripts = ScriptDirectory.from_config(config)
    unknown: list[str] = []
    for revision in MigrationContext.configure(sync_connection).get_current_heads():
        try:
            if scripts.get_revision(revision) is None:
                unknown.append(revision)
        except (CommandError, ResolutionError):
            unknown.append(revision)
    return unknown


class Database:
    def __init__(
        self,
        url: str,
        *,
        migrations_dir: Path | None = None,
        connect_args: dict[str, Any] | None = None,
        pool_size: int = 10,
        max_overflow: int = 10,
        pool_timeout: float = 5.0,
    ) -> None:
        self.engine: AsyncEngine = create_async_engine(
            url,
            pool_pre_ping=True,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
            connect_args=connect_args or {},
        )

        # Surface slow checkouts before the pool is exhausted. This records only elapsed time;
        # no query text, user data, or credentials enter logs.
        @event.listens_for(self.engine.sync_engine, "checkout")
        def _mark_checkout(_dbapi_connection, connection_record, _connection_proxy) -> None:
            connection_record.info["checked_out_at"] = time.monotonic()

        @event.listens_for(self.engine.sync_engine, "checkin")
        def _log_slow_checkout(_dbapi_connection, connection_record) -> None:
            checked_out_at = connection_record.info.pop("checked_out_at", None)
            if checked_out_at is None:
                return
            duration = time.monotonic() - checked_out_at
            if duration >= SLOW_CHECKOUT_WARNING_SEC:
                logger.warning(
                    "Database connection was checked out for %.1fs; %s",
                    duration,
                    self.engine.pool.status(),
                )

        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.store = SqlStore(self.sessions)
        self._migrations_dir = migrations_dir or Path(__file__).resolve().parents[2] / "migrations"

    async def initialize(self) -> list[UUID]:
        """Применяет миграции и возвращает безопасно восстанавливаемые прогоны."""
        async with self.engine.begin() as connection:
            config = Config()
            config.set_main_option("script_location", str(self._migrations_dir))

            def migrate(sync_connection: Any) -> None:
                unknown = unknown_db_revisions(sync_connection, config)
                if unknown:
                    # Откат релиза после применения миграций: старый код стартует поверх более
                    # новой схемы (миграции аддитивные), а не падает на «Can't locate revision».
                    logger.warning(
                        "Схема БД новее этого релиза (ревизия %s), миграции пропущены",
                        ", ".join(unknown),
                    )
                    return
                config.attributes["connection"] = sync_connection
                command.upgrade(config, "head")

            await connection.run_sync(migrate)
        recoverable: list[UUID] = []
        async with self.sessions.begin() as session:
            rows = (
                await session.scalars(
                    select(RunRow)
                    .where(RunRow.status.in_([RunStatus.QUEUED.value, RunStatus.RUNNING.value]))
                    .with_for_update()
                )
            ).all()
            for row in rows:
                # Завершённый commit версии нельзя повторять после падения между commit/status.
                if row.version_id is not None:
                    row.status = RunStatus.SUCCEEDED.value
                    row.progress = 1.0
                    row.finished_at = datetime.now(UTC)
                    continue
                ir = dict(row.ir or {})
                execution = dict(ir.get("execution", {}))
                attempts = execution.get("recovery_attempts", 0)
                if not execution.get("source_snapshot_hash") or attempts >= MAX_RUN_RECOVERIES:
                    row.status = RunStatus.FAILED.value
                    row.error = (
                        "Автовосстановление невозможно: старый запуск или лимит перезапусков"
                    )
                    row.finished_at = datetime.now(UTC)
                    continue
                execution["recovery_attempts"] = attempts + 1
                ir["execution"] = execution
                row.ir = ir
                row.status = RunStatus.QUEUED.value
                row.progress = 0.0
                row.stage = None
                row.error = None
                row.warnings = [*row.warnings, "Прогон восстановлен после перезапуска сервера"]
                recoverable.append(row.id)
        # Фоновый разбор документа жил в памяти процесса и не пережил перезапуск: без этого
        # источник остался бы в `processing` навсегда и не попадал бы в прогоны.
        await self.store.repositories().sources.fail_processing(INTERRUPTED_PARSE_ERROR)
        return recoverable

    async def seed(self, build_seed: Callable[[], Any]) -> None:
        """Идемпотентно добавляет демонстрационные проекты, не затирая пользовательские данные."""
        data = build_seed()
        repos = self.store.repositories()
        # Закрываем только известные общие примеры прежнего каталога. История и личные копии
        # остаются в БД; проект с владельцем не меняет ни видимость, ни содержимое.
        retired = getattr(data, "retired_project_ids", ())
        if retired:
            async with self.sessions.begin() as session:
                await session.execute(
                    update(ProjectRow)
                    .where(ProjectRow.id.in_(retired), ProjectRow.owner_id.is_(None))
                    .values(public_read_only=False)
                )
        for project in data.projects:
            if await repos.projects.get(project.id) is not None:
                # Демо-проект открыт на чтение всем вошедшим; чужие проекты (без сида) не трогаем.
                async with self.sessions.begin() as session:
                    await session.execute(
                        update(ProjectRow)
                        .where(ProjectRow.id == project.id, ProjectRow.owner_id.is_(None))
                        .values(public_read_only=True)
                    )
                continue
            # Проект с источниками и историей создаётся целиком: сбой не оставляет
            # частичный каталог, который следующий startup принял бы за готовый.
            async with repos.atomic() as tx:
                await tx.projects.add(project, public=True)
                for source in data.sources:
                    if source.project_id == project.id:
                        await tx.sources.add(source)
                project_runs = [run for run in data.runs if run.project_id == project.id]
                for run in project_runs:
                    # `runs.version_id` и `diagram_versions.run_id` образуют взаимную связь.
                    # Сначала создаём прогон без обратной ссылки, затем версию и обновляем прогон.
                    await tx.runs.add(replace(run, version_id=None))
                for question in data.questions:
                    if question.project_id == project.id:
                        await tx.questions.add(question)
                for version in data.versions:
                    if version.project_id == project.id:
                        await tx.versions.add(version)
                for run in project_runs:
                    if run.version_id is not None:
                        await tx.runs.update(run)

    async def check(self) -> None:
        async with self.engine.connect() as connection:
            await connection.exec_driver_sql("SELECT 1")

    async def dispose(self) -> None:
        await self.engine.dispose()


__all__ = ["Base", "Database"]
