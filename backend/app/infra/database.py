"""Подключение к PostgreSQL: жизненный цикл, миграции и сид демо-данных."""

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.domain.models import RunStatus
from app.infra.db_models import Base, ProjectRow, RunRow
from app.infra.repositories.sql import SqlStore


class Database:
    def __init__(
        self,
        url: str,
        *,
        migrations_dir: Path | None = None,
        connect_args: dict[str, Any] | None = None,
    ) -> None:
        self.engine: AsyncEngine = create_async_engine(
            url, pool_pre_ping=True, connect_args=connect_args or {}
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.store = SqlStore(self.sessions)
        self._migrations_dir = migrations_dir or Path(__file__).resolve().parents[2] / "migrations"

    async def initialize(self) -> None:
        """Применяет миграции, затем делает прерванные прогоны явными для пользователя."""
        async with self.engine.begin() as connection:
            config = Config()
            config.set_main_option("script_location", str(self._migrations_dir))

            def migrate(sync_connection: Any) -> None:
                config.attributes["connection"] = sync_connection
                command.upgrade(config, "head")

            await connection.run_sync(migrate)
        async with self.sessions.begin() as session:
            await session.execute(
                update(RunRow)
                .where(RunRow.status.in_([RunStatus.QUEUED.value, RunStatus.RUNNING.value]))
                .values(
                    status=RunStatus.FAILED.value,
                    error="Прогон прерван перезапуском сервера",
                    finished_at=datetime.now(UTC),
                )
            )

    async def seed(self, build_seed: Callable[[], Any]) -> None:
        """Идемпотентно добавляет демонстрационные проекты, не затирая пользовательские данные."""
        data = build_seed()
        repos = self.store.repositories()
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
            await repos.projects.add(project, public=True)
            for source in data.sources:
                if source.project_id == project.id:
                    await repos.sources.add(source)
            project_runs = [run for run in data.runs if run.project_id == project.id]
            for run in project_runs:
                # `runs.version_id` и `diagram_versions.run_id` образуют взаимную связь.
                # Сначала создаём прогон без обратной ссылки, затем версию и обновляем прогон.
                await repos.runs.add(replace(run, version_id=None))
            for question in data.questions:
                if question.project_id == project.id:
                    await repos.questions.add(question)
            for version in data.versions:
                if version.project_id == project.id:
                    await repos.versions.add(version)
            for run in project_runs:
                if run.version_id is not None:
                    await repos.runs.update(run)

    async def check(self) -> None:
        async with self.engine.connect() as connection:
            await connection.exec_driver_sql("SELECT 1")

    async def dispose(self) -> None:
        await self.engine.dispose()


__all__ = ["Base", "Database"]
