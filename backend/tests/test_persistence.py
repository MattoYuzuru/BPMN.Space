"""Проверки схемы и persistent storage; SQL-тест требует TEST_DATABASE_URL."""

import asyncio
import os
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Table, inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.domain.models import (
    LlmCall,
    Project,
    Run,
    RunMode,
    RunStatus,
    Source,
    SourceKind,
    SourceStatus,
)
from app.fixtures import read_bpmn
from app.fixtures.playbook import PLAYBOOK
from app.infra.bpmn_tools import MockBpmnTools
from app.infra.database import Database
from app.infra.db_models import (
    Base,
    DiagramVersionRow,
    LlmCallRow,
    QuestionRow,
    RunRow,
    SourceRow,
)
from app.infra.events import InMemoryRunEventBus
from app.infra.repositories.base import ActiveRunConflictError
from app.infra.repositories.sql import SqlRunRepository, SqlStore
from app.infra.seed import DEMO_PROJECT_ID, build_seed
from app.infra.storage import LocalFileStorage
from app.infra.tasks import AsyncioTaskSpawner
from app.llm.mock import MockPipeline
from app.services.common import Runtime
from app.services.errors import ConflictError
from app.services.runs import RunService

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


@pytest.fixture
async def sql_store() -> AsyncIterator[tuple[SqlStore, async_sessionmaker[AsyncSession]]]:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL не задан; PostgreSQL-интеграционный тест пропущен")

    schema = f"test_{uuid4().hex}"
    admin_engine = create_async_engine(url)
    async with admin_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    migration_config = Config()
    migration_config.set_main_option("script_location", str(MIGRATIONS_DIR))
    async with engine.begin() as connection:

        def upgrade(sync_connection) -> None:
            migration_config.attributes["connection"] = sync_connection
            command.upgrade(migration_config, "head")

        await connection.run_sync(upgrade)

    try:
        yield SqlStore(sessions), sessions
    finally:
        await engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin_engine.dispose()


def test_postgres_schema_has_domain_tables_and_active_run_constraint() -> None:
    assert {
        "projects",
        "sources",
        "questions",
        "runs",
        "diagram_versions",
        "llm_calls",
    } <= set(Base.metadata.tables)
    runs_table = cast(Table, RunRow.__table__)
    active_run_index = next(
        index for index in runs_table.indexes if index.name == "uq_runs_active_project"
    )
    assert active_run_index.unique
    assert "queued" in str(active_run_index.dialect_options["postgresql"]["where"])
    assert "running" in str(active_run_index.dialect_options["postgresql"]["where"])

    question_table = cast(Table, QuestionRow.__table__)
    version_table = cast(Table, DiagramVersionRow.__table__)
    question_constraints = {constraint.name for constraint in question_table.constraints}
    version_constraints = {constraint.name for constraint in version_table.constraints}
    run_foreign_keys = {foreign_key.name for foreign_key in RunRow.__table__.foreign_keys}
    assert "uq_questions_answer_source_id" in question_constraints
    assert "uq_versions_run_id" in version_constraints
    assert "fk_runs_version_id_diagram_versions" in run_foreign_keys


@pytest.mark.asyncio
async def test_postgres_migration_installs_one_to_one_constraints(sql_store) -> None:
    _, sessions = sql_store
    async with sessions() as session:
        connection = await session.connection()

        def constraints(sync_connection):
            inspector = inspect(sync_connection)
            return (
                {item["name"] for item in inspector.get_unique_constraints("questions")},
                {item["name"] for item in inspector.get_unique_constraints("diagram_versions")},
                {item["name"] for item in inspector.get_foreign_keys("runs")},
            )

        questions, versions, runs = await connection.run_sync(constraints)
    assert "uq_questions_answer_source_id" in questions
    assert "uq_versions_run_id" in versions
    assert "fk_runs_version_id_diagram_versions" in runs


@pytest.mark.asyncio
async def test_database_seed_persists_linked_runs_and_versions(sql_store) -> None:
    store, _ = sql_store
    database = Database(os.environ["TEST_DATABASE_URL"])
    database.store = store
    try:
        await database.seed(build_seed)
        await database.seed(build_seed)
        repos = store.repositories()
        seeded = build_seed()
        linked_run = next(run for run in seeded.runs if run.version_id is not None)
        restored_run = await repos.runs.get(linked_run.id)
        restored_version = await repos.versions.get(linked_run.version_id)
        assert restored_run is not None
        assert restored_run.version_id == linked_run.version_id
        assert restored_version is not None
        assert restored_version.run_id == linked_run.id
        assert await repos.projects.get(DEMO_PROJECT_ID) is not None
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_local_file_storage_persists_and_rejects_path_escape(tmp_path) -> None:
    project_id = uuid4()
    first_instance = LocalFileStorage(tmp_path)
    key = await first_instance.save(project_id=project_id, file_name="input.txt", data=b"stored")

    restarted_instance = LocalFileStorage(tmp_path)
    assert await restarted_instance.load(key) == b"stored"

    with pytest.raises(ValueError, match="Недопустимый ключ"):
        await restarted_instance.load("../outside.txt")

    await restarted_instance.delete(key)
    with pytest.raises(FileNotFoundError):
        await first_instance.load(key)


@pytest.mark.asyncio
async def test_postgres_repositories_persist_artifacts_and_enforce_active_run(sql_store) -> None:
    store, sessions = sql_store
    repos = store.repositories()
    now = datetime.now(UTC)
    project = Project(
        id=uuid4(), title="Проверка PostgreSQL", description=None, created_at=now, updated_at=now
    )
    source = Source(
        id=uuid4(),
        project_id=project.id,
        kind=SourceKind.TEXT,
        title="Регламент",
        content="Исходный текст",
        status=SourceStatus.READY,
        active=True,
        created_at=now,
        digest="Короткая выжимка",
    )
    run = Run(
        id=uuid4(),
        project_id=project.id,
        mode=RunMode.ANALYZE,
        status=RunStatus.QUEUED,
        started_at=now,
        model="recorded-fixtures",
        analysis={"new_questions": []},
        ir={"steps": []},
        report={"xsd_valid": True},
        latency_ms=123,
    )
    await repos.projects.add(project)
    await repos.sources.add(source)
    await repos.runs.add(run)
    await repos.llm_calls.add(
        LlmCall(
            id=uuid4(),
            run_id=run.id,
            stage="analyze",
            request={"context": "Исходный текст"},
            response={"new_questions": []},
            latency_ms=42,
        )
    )

    restored_run = await repos.runs.get(run.id)
    restored_source = await repos.sources.get(source.id)
    assert restored_run is not None
    assert restored_run.analysis == {"new_questions": []}
    assert restored_run.ir == {"steps": []}
    assert restored_run.report == {"xsd_valid": True}
    assert restored_run.model == "recorded-fixtures"
    assert restored_run.latency_ms == 123
    assert restored_source is not None
    assert restored_source.digest == "Короткая выжимка"

    async with sessions() as session:
        saved_call = await session.scalar(select(LlmCallRow).where(LlmCallRow.run_id == run.id))
        db_run = await session.get(RunRow, run.id)
        db_source = await session.get(SourceRow, source.id)
    assert saved_call is not None
    assert saved_call.stage == "analyze"
    assert db_run is not None
    assert db_run.summary is None
    assert db_source is not None
    assert db_source.digest == "Короткая выжимка"

    conflicting_run = Run(
        id=uuid4(),
        project_id=project.id,
        mode=RunMode.BUILD,
        status=RunStatus.RUNNING,
        started_at=now,
    )
    with pytest.raises(ActiveRunConflictError):
        await SqlRunRepository(sessions).add(conflicting_run)


@pytest.mark.asyncio
async def test_run_service_persists_pipeline_calls_and_final_artifacts(sql_store) -> None:
    store, sessions = sql_store
    repos = store.repositories()
    now = datetime.now(UTC)
    project = Project(
        id=uuid4(), title="Сквозной SQL прогон", description=None, created_at=now, updated_at=now
    )
    source = Source(
        id=uuid4(),
        project_id=project.id,
        kind=SourceKind.TEXT,
        title="Регламент",
        content=(
            "Порядок действий:\n"
            "1. Принять заявку. Ответственный: оператор.\n"
            "2. Согласовать заявку. Ответственный: руководитель."
        ),
        status=SourceStatus.READY,
        active=True,
        created_at=now,
    )
    await repos.projects.add(project)
    await repos.sources.add(source)

    spawner = AsyncioTaskSpawner()
    service = RunService(
        repos,
        pipeline=MockPipeline(playbook=PLAYBOOK, read_bpmn=read_bpmn),
        bpmn_tools=MockBpmnTools(),
        events=InMemoryRunEventBus(),
        spawner=spawner,
        runtime=Runtime(),
        max_concurrent=1,
    )
    started = await service.start(project.id, mode=RunMode.BUILD)
    await spawner.wait_idle()

    saved = await repos.runs.get(started.id)
    assert saved is not None
    assert saved.status is RunStatus.SUCCEEDED
    assert saved.analysis is not None
    assert saved.report is not None
    assert saved.report["xsd_valid"] is True
    assert saved.version_id is not None
    assert saved.model == "recorded-fixtures"
    assert saved.latency_ms is not None

    async with sessions() as session:
        calls = (
            await session.scalars(select(LlmCallRow).where(LlmCallRow.run_id == started.id))
        ).all()
    assert {call.stage for call in calls} == {"analyze", "structure"}
    assert all(call.request and call.response and call.latency_ms is not None for call in calls)


@pytest.mark.asyncio
async def test_database_index_race_becomes_http_service_conflict(sql_store) -> None:
    store, sessions = sql_store
    repos = store.repositories()
    now = datetime.now(UTC)
    project = Project(
        id=uuid4(), title="Гонка прогонов", description=None, created_at=now, updated_at=now
    )
    source = Source(
        id=uuid4(),
        project_id=project.id,
        kind=SourceKind.TEXT,
        title="Регламент",
        content="Оператор принимает заявку. Руководитель согласует заявку.",
        status=SourceStatus.READY,
        active=True,
        created_at=now,
    )
    await repos.projects.add(project)
    await repos.sources.add(source)
    release_first_run = asyncio.Event()

    async def hold_run(_stage) -> None:
        await release_first_run.wait()

    pipeline = MockPipeline(playbook=PLAYBOOK, read_bpmn=read_bpmn)
    first_spawner = AsyncioTaskSpawner()
    first_service = RunService(
        repos,
        pipeline=pipeline,
        bpmn_tools=MockBpmnTools(),
        events=InMemoryRunEventBus(),
        spawner=first_spawner,
        runtime=Runtime(),
        max_concurrent=1,
        pace=hold_run,
    )

    class StaleReadRunRepository(SqlRunRepository):
        async def active_for_project(self, project_id):
            return None

    racing_repos = replace(repos, runs=StaleReadRunRepository(sessions))
    second_service = RunService(
        racing_repos,
        pipeline=pipeline,
        bpmn_tools=MockBpmnTools(),
        events=InMemoryRunEventBus(),
        spawner=AsyncioTaskSpawner(),
        runtime=Runtime(),
        max_concurrent=1,
    )

    started = await first_service.start(project.id, mode=RunMode.ANALYZE)
    await asyncio.sleep(0)
    with pytest.raises(ConflictError, match="уже идёт"):
        await second_service.start(project.id, mode=RunMode.BUILD)

    release_first_run.set()
    await first_spawner.wait_idle()
    finished = await repos.runs.get(started.id)
    assert finished is not None
    assert finished.status is RunStatus.SUCCEEDED
