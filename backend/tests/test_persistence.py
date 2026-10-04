"""Проверки схемы и persistent storage; SQL-тест требует TEST_DATABASE_URL."""

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Table, func, inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.container import build_container
from app.domain.models import (
    LlmCall,
    Project,
    Run,
    RunMode,
    RunStatus,
    Source,
    SourceKind,
    SourceStatus,
    VersionOrigin,
)
from app.fixtures import read_bpmn
from app.fixtures.playbook import PLAYBOOK
from app.infra.bpmn_tools import MockBpmnTools
from app.infra.database import Database
from app.infra.db_models import (
    AccessTokenRow,
    Base,
    DiagramVersionRow,
    LlmCallRow,
    ProjectMemberRow,
    ProjectShareLinkRow,
    QuestionRow,
    RunRow,
    SourceRow,
    UserRow,
)
from app.infra.events import InMemoryRunEventBus
from app.infra.repositories.base import ActiveRunConflictError
from app.infra.repositories.sql import SqlRunRepository, SqlStore
from app.infra.seed import DEMO_PROJECT_ID, build_seed
from app.infra.storage import LocalFileStorage
from app.infra.tasks import AsyncioTaskSpawner
from app.llm.mock import MockPipeline
from app.main import create_app
from app.services.access import AccessService, ProjectRole
from app.services.common import Runtime
from app.services.errors import ConflictError, NotFoundError
from app.services.projects import ProjectService
from app.services.runs import RunService
from app.services.sharing import SharingService
from app.services.versions import VersionService, add_version

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
async def test_auth_register_login_me_logout_and_hashed_session(sql_store) -> None:
    store, sessions = sql_store
    database = Database(os.environ["TEST_DATABASE_URL"])
    database.store = store
    database.sessions = sessions
    settings = Settings(auth_enabled=True, database_url=None, seed_demo_data=False)
    container = replace(build_container(settings), database=database)
    app = create_app(settings, container=container)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        csrf_response = await client.get("/api/v1/auth/csrf")
        csrf = csrf_response.json()["csrf_token"]
        headers = {"x-csrf-token": csrf}
        registration = await client.post(
            "/api/v1/auth/register",
            json={"email": "analyst@example.com", "password": "test-password-long-enough"},
            headers=headers,
        )
        assert registration.status_code == 201, registration.text
        assert registration.json()["email"] == "analyst@example.com"
        assert "is_superuser" not in registration.json()

        login = await client.post(
            "/api/v1/auth/session/login",
            data={"username": "analyst@example.com", "password": "test-password-long-enough"},
            headers=headers,
        )
        assert login.status_code == 204, login.text
        session_cookie = client.cookies.get("arkhitektor_session")
        assert session_cookie

        async with sessions() as session:
            saved_session = await session.scalar(select(AccessTokenRow))
            user = await session.scalar(select(UserRow))
        assert saved_session is not None
        assert saved_session.token != session_cookie
        assert len(saved_session.token) == 43
        assert user is not None
        assert user.hashed_password.startswith("$argon2")

        profile = await client.get("/api/v1/auth/me")
        assert profile.status_code == 200
        assert profile.json() == {"id": str(user.id), "email": "analyst@example.com"}

        logout = await client.post("/api/v1/auth/session/logout", headers=headers)
        assert logout.status_code == 204
        profile = await client.get("/api/v1/auth/me")
        assert profile.status_code == 401
    await database.dispose()


@pytest.mark.asyncio
async def test_editor_share_acceptance_is_account_scoped_and_revocable(sql_store) -> None:
    store, sessions = sql_store
    runtime = Runtime()
    access = AccessService(store.repositories().access, runtime=runtime)
    sharing = SharingService(access, runtime=runtime)
    now = datetime.now(UTC)
    owner = UserRow(
        id=uuid4(),
        email="owner@example.com",
        hashed_password=uuid4().hex,
        is_active=True,
        is_superuser=False,
        is_verified=False,
    )
    editor = UserRow(
        id=uuid4(),
        email="editor@example.com",
        hashed_password=uuid4().hex,
        is_active=True,
        is_superuser=False,
        is_verified=False,
    )
    async with sessions.begin() as session:
        session.add_all([owner, editor])
    project = Project(
        id=uuid4(), title="Shared project", description=None, created_at=now, updated_at=now
    )
    await store.repositories().projects.add(project, owner_id=owner.id)

    created = await sharing.create_link(
        project.id, role="editor", expires_in_days=None, created_by=owner.id
    )
    link = await access.active_link(created.token)
    assert link.id == created.link.id
    assert link.token_hash != created.token
    assert await access.project_role(project.id, editor.id) is None

    await sharing.accept_invite(project.id, editor.id)
    assert await access.project_role(project.id, editor.id) == ProjectRole.EDITOR
    async with sessions() as session:
        membership = await session.get(ProjectMemberRow, (project.id, editor.id))
        stored_link = await session.get(ProjectShareLinkRow, link.id)
    assert membership is not None
    assert membership.role == "editor"
    assert stored_link is not None
    assert stored_link.token_hash != created.token

    await sharing.remove_member(project.id, editor.id)
    assert await access.project_role(project.id, editor.id) is None
    await sharing.revoke_link(project.id, link.id)
    with pytest.raises(NotFoundError):
        await access.active_link(created.token)


@pytest.mark.asyncio
async def test_database_seed_persists_linked_runs_and_versions(sql_store) -> None:
    store, sessions = sql_store
    database = Database(os.environ["TEST_DATABASE_URL"])
    database.store = store
    database.sessions = sessions
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


# ---------- единица работы и конкурентность ----------


async def _make_project(repos, title: str = "Конкурентность") -> Project:
    now = datetime.now(UTC)
    project = Project(id=uuid4(), title=title, description=None, created_at=now, updated_at=now)
    await repos.projects.add(project)
    return project


@pytest.mark.asyncio
async def test_concurrent_versions_get_consecutive_numbers(sql_store) -> None:
    store, _ = sql_store
    repos = store.repositories()
    project = await _make_project(repos)
    xml = read_bpmn("tp861_v2")
    service = VersionService(
        repos, bpmn_tools=MockBpmnTools(), runtime=Runtime(), max_diagram_bytes=5 * 1024 * 1024
    )

    async def manual() -> int:
        return (await service.save_manual(project.id, xml=xml)).number

    async def generated() -> int:
        version = await add_version(
            repos,
            Runtime(),
            project_id=project.id,
            xml=xml,
            origin=VersionOrigin.GENERATED,
            lint=[],
            trace={},
        )
        return version.number

    # Ручные сохранения двух редакторов и версии от прогонов приходят одновременно.
    numbers = await asyncio.gather(*(manual() if i % 2 else generated() for i in range(10)))
    assert sorted(numbers) == list(range(1, 11))
    latest = await repos.versions.latest(project.id)
    assert latest is not None
    assert latest.number == 10


@pytest.mark.asyncio
async def test_manual_save_conflicts_with_active_run_in_postgres(sql_store) -> None:
    store, _ = sql_store
    repos = store.repositories()
    project = await _make_project(repos)
    await repos.runs.add(
        Run(
            id=uuid4(),
            project_id=project.id,
            mode=RunMode.BUILD,
            status=RunStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
    )
    service = VersionService(
        repos, bpmn_tools=MockBpmnTools(), runtime=Runtime(), max_diagram_bytes=5 * 1024 * 1024
    )
    with pytest.raises(ConflictError, match="идёт сборка"):
        await service.save_manual(project.id, xml=read_bpmn("tp861_v2"))
    assert await repos.versions.latest(project.id) is None


@pytest.mark.asyncio
async def test_reconciled_question_write_is_conditional_in_postgres(sql_store) -> None:
    from app.domain.models import (  # noqa: PLC0415
        Question,
        QuestionKind,
        QuestionStatus,
        Severity,
    )

    store, _ = sql_store
    repos = store.repositories()
    project = await _make_project(repos)
    now = datetime.now(UTC)
    question = Question(
        id=uuid4(),
        project_id=project.id,
        code="Q-1",
        kind=QuestionKind.MISSING_ACTOR,
        severity=Severity.MAJOR,
        status=QuestionStatus.OPEN,
        text="Кто принимает заявку?",
        assumption="",
        created_at=now,
        updated_at=now,
    )
    await repos.questions.add(question)
    stale = await repos.questions.get(question.id)
    assert stale is not None

    question.status = QuestionStatus.ANSWERED  # аналитик ответил между чтением и записью
    await repos.questions.update(question)
    stale.status = QuestionStatus.RESOLVED
    assert not await repos.questions.apply_reconciled(stale, expected_status=QuestionStatus.OPEN)
    kept = await repos.questions.get(question.id)
    assert kept is not None
    assert kept.status is QuestionStatus.ANSWERED

    assert await repos.questions.apply_reconciled(stale, expected_status=QuestionStatus.ANSWERED)
    updated = await repos.questions.get(question.id)
    assert updated is not None
    assert updated.status is QuestionStatus.RESOLVED


@pytest.mark.asyncio
async def test_atomic_block_rolls_back_every_repository(sql_store) -> None:
    store, _ = sql_store
    repos = store.repositories()
    project = await _make_project(repos)
    source = Source(
        id=uuid4(),
        project_id=project.id,
        kind=SourceKind.TEXT,
        title="Текст",
        content="Текст",
        status=SourceStatus.READY,
        active=True,
        created_at=datetime.now(UTC),
    )

    async def failing_unit() -> None:
        async with repos.atomic() as tx:
            await tx.sources.add(source)
            await tx.projects.delete(project.id)
            raise RuntimeError("сбой")

    with pytest.raises(RuntimeError, match="сбой"):
        await failing_unit()
    assert await repos.projects.get(project.id) is not None
    assert await repos.sources.get(source.id) is None

    async with repos.atomic() as tx:
        await tx.sources.add(source)
        async with tx.atomic() as nested:  # вложенный atomic — та же транзакция
            assert nested is tx
    assert await repos.sources.get(source.id) is not None


@pytest.mark.asyncio
async def test_project_delete_is_atomic_and_cascades(sql_store, tmp_path) -> None:
    store, sessions = sql_store
    repos = store.repositories()
    seeded = build_seed()
    project = seeded.projects[0]
    await repos.projects.add(project)
    for source in (s for s in seeded.sources if s.project_id == project.id):
        await repos.sources.add(source)
    runs = [r for r in seeded.runs if r.project_id == project.id]
    for run in runs:
        await repos.runs.add(replace(run, version_id=None))
    for question in (q for q in seeded.questions if q.project_id == project.id):
        await repos.questions.add(question)
    for version in (v for v in seeded.versions if v.project_id == project.id):
        await repos.versions.add(version)
    await repos.llm_calls.add(
        LlmCall(id=uuid4(), run_id=runs[0].id, stage="analyze", request={}, response={})
    )
    service = ProjectService(
        repos, examples=[], runtime=Runtime(), storage=LocalFileStorage(tmp_path)
    )

    await service.delete(project.id)

    async with sessions() as session:
        for table in (SourceRow, QuestionRow, RunRow, DiagramVersionRow, LlmCallRow):
            count = await session.scalar(select(func.count()).select_from(table))
            assert count == 0, table
    assert await repos.projects.get(project.id) is None
    with pytest.raises(NotFoundError):
        await service.delete(project.id)


@pytest.mark.asyncio
async def test_project_delete_refuses_active_run_without_partial_delete(
    sql_store, tmp_path
) -> None:
    store, _ = sql_store
    repos = store.repositories()
    project = await _make_project(repos)
    await repos.runs.add(
        Run(
            id=uuid4(),
            project_id=project.id,
            mode=RunMode.ANALYZE,
            status=RunStatus.QUEUED,
            started_at=datetime.now(UTC),
        )
    )
    service = ProjectService(
        repos, examples=[], runtime=Runtime(), storage=LocalFileStorage(tmp_path)
    )
    with pytest.raises(ConflictError):
        await service.delete(project.id)
    assert await repos.projects.get(project.id) is not None
    assert await repos.runs.active_for_project(project.id) is not None


@pytest.mark.asyncio
async def test_source_patch_is_targeted_and_conditional(sql_store) -> None:
    store, _ = sql_store
    repos = store.repositories()
    project = await _make_project(repos)
    source = Source(
        id=uuid4(),
        project_id=project.id,
        kind=SourceKind.FILE,
        title="Файл",
        content="",
        status=SourceStatus.PROCESSING,
        active=True,
        created_at=datetime.now(UTC),
        file_name="a.pdf",
    )
    await repos.sources.add(source)
    # Пользователь переименовал и выключил источник, пока шёл разбор.
    assert await repos.sources.patch(source.id, {"title": "Новое", "active": False})
    # Разбор записывает только свои поля и только пока источник в processing.
    assert await repos.sources.patch(
        source.id,
        {"status": SourceStatus.READY, "content": "Текст", "error": None},
        only_status=SourceStatus.PROCESSING,
    )
    stored = await repos.sources.get(source.id)
    assert stored is not None
    assert (stored.title, stored.active, stored.status) == ("Новое", False, SourceStatus.READY)
    assert stored.file_name == "a.pdf"
    assert not await repos.sources.patch(
        source.id, {"status": SourceStatus.FAILED}, only_status=SourceStatus.PROCESSING
    )
    assert not await repos.sources.patch(uuid4(), {"active": True})
    with pytest.raises(ValueError, match="нельзя менять"):
        await repos.sources.patch(source.id, {"project_id": uuid4()})
    with pytest.raises(ValueError, match="Не указаны"):
        await repos.sources.patch(source.id, {})


@pytest.mark.asyncio
async def test_fail_processing_and_project_touch_update(sql_store) -> None:
    store, _ = sql_store
    repos = store.repositories()
    project = await _make_project(repos)
    for status in (SourceStatus.PROCESSING, SourceStatus.READY):
        await repos.sources.add(
            Source(
                id=uuid4(),
                project_id=project.id,
                kind=SourceKind.FILE,
                title=status.value,
                content="",
                status=status,
                active=True,
                created_at=datetime.now(UTC),
            )
        )
    assert await repos.sources.fail_processing("Прервано") == 1
    sources = {s.title: s for s in await repos.sources.list_by_project(project.id)}
    assert sources["processing"].status is SourceStatus.FAILED
    assert sources["processing"].error == "Прервано"
    assert sources["ready"].status is SourceStatus.READY

    later = project.updated_at + timedelta(hours=1)
    await repos.projects.touch(project.id, later)
    await repos.projects.touch(project.id, project.updated_at)  # назад время не идёт
    renamed = replace(project, title="Другое имя", updated_at=project.updated_at)
    await repos.projects.update(renamed)  # `update` не трогает updated_at
    stored = await repos.projects.get(project.id)
    assert stored is not None
    assert stored.title == "Другое имя"
    assert stored.updated_at == later


@pytest.mark.asyncio
async def test_run_warnings_and_llm_tokens_round_trip(sql_store) -> None:
    store, sessions = sql_store
    repos = store.repositories()
    project = await _make_project(repos)
    run = Run(
        id=uuid4(),
        project_id=project.id,
        mode=RunMode.ANALYZE,
        status=RunStatus.SUCCEEDED,
        started_at=datetime.now(UTC),
        warnings=["Источник обрезан"],
    )
    await repos.runs.add(run)
    await repos.llm_calls.add(
        LlmCall(
            id=uuid4(),
            run_id=run.id,
            stage="analyze",
            request={"context": {"sources": []}},
            response={},
            tokens_in=120,
            tokens_out=30,
        )
    )
    stored = await repos.runs.get(run.id)
    assert stored is not None
    assert stored.warnings == ["Источник обрезан"]
    run.warnings = []
    await repos.runs.update(run)
    again = await repos.runs.get(run.id)
    assert again is not None
    assert again.warnings == []
    async with sessions() as session:
        call = await session.scalar(select(LlmCallRow).where(LlmCallRow.run_id == run.id))
    assert call is not None
    assert (call.tokens_in, call.tokens_out) == (120, 30)


@pytest.mark.asyncio
async def test_initialize_skips_upgrade_for_newer_schema(
    caplog: pytest.LogCaptureFixture,
) -> None:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL не задан; PostgreSQL-интеграционный тест пропущен")
    schema = f"test_{uuid4().hex}"
    admin = create_async_engine(url)
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    database = Database(url, connect_args={"server_settings": {"search_path": schema}})
    try:
        await database.initialize()  # применили все миграции этого релиза
        async with database.engine.begin() as connection:
            await connection.execute(text("UPDATE alembic_version SET version_num = '9999_future'"))
        caplog.set_level(logging.WARNING, logger="app.infra.database")
        await database.initialize()  # старый релиз поверх более новой схемы не падает
        assert "9999_future" in caplog.text
        assert "Схема БД новее" in caplog.text
        async with database.engine.connect() as connection:
            version = (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
        assert version == "9999_future"  # чужую ревизию не трогаем
    finally:
        await database.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()
