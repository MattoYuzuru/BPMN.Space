"""Сессии правок (ADR-0010): слияние автосохранений, контрольные точки, страницы истории.

Один набор сценариев идёт по обоим репозиториям: в памяти и в PostgreSQL (если задан
`TEST_DATABASE_URL`).
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.domain.models import (
    Project,
    Quote,
    Run,
    RunMode,
    RunStatus,
    Version,
    VersionOrigin,
)
from app.fixtures import read_bpmn
from app.infra.bpmn_tools import MockBpmnTools
from app.infra.db_models import DiagramVersionRow
from app.infra.repositories.base import Repositories
from app.infra.repositories.memory import InMemoryStore
from app.services.common import Runtime
from app.services.errors import InvalidInputError, NotFoundError, StaleVersionError
from app.services.versions import VersionService, add_version
from tests.test_persistence import sql_test_store

ALICE = "alice@example.com"
BOB = "bob@example.com"
START = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture(params=["memory", "sql"])
async def repos(request: pytest.FixtureRequest) -> AsyncIterator[Repositories]:
    if request.param == "memory":
        yield InMemoryStore().repositories()
    else:
        async with sql_test_store() as (store, _):
            yield store.repositories()


class Setup:
    def __init__(self, repos: Repositories) -> None:
        self.repos = repos
        self.clock = Clock()
        self.runtime = Runtime(clock=self.clock)
        self.xml = read_bpmn("tp861_v2")
        self.service = VersionService(
            repos,
            bpmn_tools=MockBpmnTools(),
            runtime=self.runtime,
            max_diagram_bytes=5 * 1024 * 1024,
            session_idle_sec=600,
            session_max_sec=3600,
        )
        self.project_id: UUID

    async def start(self) -> Version:
        project = Project(
            id=uuid4(), title="Сессии", description=None, created_at=START, updated_at=START
        )
        await self.repos.projects.add(project)
        self.project_id = project.id
        source_id = uuid4()
        return await add_version(
            self.repos,
            self.runtime,
            project_id=project.id,
            xml=self.xml,
            origin=VersionOrigin.GENERATED,
            lint=[],
            trace={"Task_CheckCompleteness": Quote(source_id=source_id, quote="Проверка полноты")},
        )

    async def head(self) -> Version:
        head = await self.repos.versions.latest(self.project_id)
        assert head is not None
        return head

    async def edit(self, n: int, *, actor: str | None = ALICE) -> Version:
        head = await self.head()
        return await self.service.save_manual(
            self.project_id,
            xml=self.xml.replace("Провести выездной осмотр", f"Осмотр {n}"),
            base_version_id=head.id,
            actor_email=actor,
        )

    async def count(self) -> int:
        return len(await self.repos.versions.list_by_project(self.project_id, include_xml=False))


@pytest.fixture
async def setup(repos: Repositories) -> Setup:
    state = Setup(repos)
    await state.start()
    return state


async def test_same_author_autosaves_coalesce_into_one_version(setup: Setup) -> None:
    first = await setup.edit(1)
    assert first.number == 2
    assert first.saved_count == 1
    setup.clock.advance(30)
    second = await setup.edit(2)
    setup.clock.advance(30)
    third = await setup.edit(3)

    assert third.number == 2
    assert len({first.id, second.id, third.id}) == 3  # новый id: base_version_id устаревает
    assert third.saved_count == 3
    assert third.created_at == first.created_at
    assert third.session_started_at == first.session_started_at
    assert third.updated_at == START + timedelta(seconds=60)
    assert await setup.count() == 2
    stored = await setup.repos.versions.get(third.id)
    assert stored is not None
    assert "Осмотр 3" in stored.xml
    assert await setup.repos.versions.get(first.id) is None
    # Дифф считается от предшественника сессии, а не от промежуточного автосохранения.
    assert (third.diff.added, third.diff.removed, third.diff.changed) == (0, 0, 1)


async def test_stale_base_after_coalescing_is_a_conflict(setup: Setup) -> None:
    first = await setup.edit(1)
    setup.clock.advance(10)
    await setup.edit(2)
    with pytest.raises(StaleVersionError):
        await setup.service.save_manual(
            setup.project_id,
            xml=setup.xml.replace("Провести выездной осмотр", "Осмотр 9"),
            base_version_id=first.id,
            actor_email=ALICE,
        )


@pytest.mark.parametrize(
    "scenario", ["other_author", "idle", "max_duration", "anonymous", "checkpoint"]
)
async def test_new_version_is_started(setup: Setup, scenario: str) -> None:
    first = await setup.edit(1, actor=None if scenario == "anonymous" else ALICE)
    if scenario == "idle":
        setup.clock.advance(601)
    elif scenario == "max_duration":
        for n in range(2, 8):  # каждые 590 с сессия жива, но превышает час
            setup.clock.advance(590)
            await setup.edit(n)
        head = await setup.head()
        assert head.number == 2
        setup.clock.advance(100)
        first = head
    else:
        setup.clock.advance(5)
    if scenario == "checkpoint":
        marked = await setup.service.checkpoint(setup.project_id, first.id, label="Согласовано")
        assert marked.checkpoint
        assert marked.label == "Согласовано"
    second = await setup.edit(
        99, actor=BOB if scenario == "other_author" else None if scenario == "anonymous" else ALICE
    )
    assert second.number == first.number + 1
    assert second.saved_count == 1
    previous = await setup.repos.versions.get(first.id)
    assert previous is not None  # прежняя версия осталась в истории


async def test_generated_version_closes_the_session(setup: Setup) -> None:
    await setup.edit(1)
    await add_version(
        setup.repos,
        setup.runtime,
        project_id=setup.project_id,
        xml=setup.xml,
        origin=VersionOrigin.GENERATED,
        lint=[],
        trace={},
        run_id=None,
    )
    assert (await setup.head()).number == 3
    after = await setup.edit(2)
    assert after.number == 4


async def test_version_with_dependants_is_not_replaced(setup: Setup) -> None:
    first = await setup.edit(1)
    await setup.repos.runs.add(
        Run(
            id=uuid4(),
            project_id=setup.project_id,
            mode=RunMode.ANALYZE,
            status=RunStatus.SUCCEEDED,
            started_at=START,
            version_id=first.id,
        )
    )
    setup.clock.advance(10)
    second = await setup.edit(2)
    assert second.number == first.number + 1
    assert await setup.repos.versions.get(first.id) is not None


async def test_identical_save_is_idempotent(setup: Setup) -> None:
    first = await setup.edit(1)
    setup.clock.advance(5)
    again = await setup.edit(1)
    assert again.id == first.id
    assert again.saved_count == 1


async def test_checkpoint_rules(setup: Setup) -> None:
    head = await setup.edit(1)
    with pytest.raises(InvalidInputError):
        await setup.service.checkpoint(setup.project_id, head.id, label="я" * 121)
    with pytest.raises(NotFoundError):
        await setup.service.checkpoint(setup.project_id, uuid4())
    named = await setup.service.checkpoint(setup.project_id, head.id, label="  v1  ")
    assert named.label == "v1"
    again = await setup.service.checkpoint(setup.project_id, head.id)  # идемпотентно
    assert again.checkpoint
    assert again.label == "v1"


async def test_history_pages_use_cursor_and_are_slim(setup: Setup) -> None:
    for n in range(1, 6):
        setup.clock.advance(700)  # каждая правка — новая сессия
        await setup.edit(n)
    first, cursor = await setup.service.list_page(setup.project_id, limit=2)
    assert [v.number for v in first] == [6, 5]
    assert cursor == 5
    second, cursor = await setup.service.list_page(setup.project_id, limit=2, before=cursor)
    assert [v.number for v in second] == [4, 3]
    assert cursor == 3
    last, cursor = await setup.service.list_page(setup.project_id, limit=5, before=cursor)
    assert [v.number for v in last] == [2, 1]
    assert cursor is None
    assert last[1].origin is VersionOrigin.GENERATED
    assert not hasattr(first[0], "xml")
    assert not hasattr(first[0], "trace")


async def test_metadata_is_resolved_from_the_owning_version(setup: Setup) -> None:
    generated = await setup.head()
    assert generated.trace
    for n in range(1, 4):
        setup.clock.advance(700)
        await setup.edit(n)
    head = await setup.head()
    assert head.number == 4
    assert head.trace == generated.trace
    assert head.report == (await setup.repos.versions.by_number(setup.project_id, 3)).report  # type: ignore[union-attr]
    listed = await setup.repos.versions.list_by_project(setup.project_id, include_xml=False)
    assert all(v.trace == generated.trace for v in listed)


async def test_sql_shares_unchanged_trace_and_report() -> None:
    async with sql_test_store() as (store, sessions):
        state = Setup(store.repositories())
        await state.start()
        for n in range(1, 4):
            state.clock.advance(700)
            await state.edit(n)
        async with sessions() as session:
            rows = (
                await session.scalars(
                    select(DiagramVersionRow)
                    .where(DiagramVersionRow.project_id == state.project_id)
                    .order_by(DiagramVersionRow.number)
                )
            ).all()
    assert [(r.trace_inherited, r.report_inherited) for r in rows] == [
        (False, False),
        (True, True),
        (True, True),
        (True, True),
    ]
    assert all(r.trace == {} and r.report == {} for r in rows[1:])
    assert rows[0].trace
    assert rows[3].lint_count == rows[0].lint_count
