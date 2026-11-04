"""Агрегаты карточек проектов: память и PostgreSQL дают одинаковый ответ без N+1."""

import os

import pytest
from sqlalchemy import event

from app.domain.models import QuestionStatus, SourceKind, SourceStatus
from app.domain.runs import ACTIVE_STATUSES
from app.infra.database import Database
from app.infra.repositories.memory import InMemoryStore
from app.infra.repositories.sql import SqlStore
from app.infra.seed import build_seed
from tests.test_persistence import sql_store  # noqa: F401 — фикстура схемы PostgreSQL


def _expected(seed):
    result = {}
    for project in seed.projects:
        sources = [
            s
            for s in seed.sources
            if s.project_id == project.id and s.kind is not SourceKind.ANSWER
        ]
        questions = [q for q in seed.questions if q.project_id == project.id]
        versions = sorted(
            (v for v in seed.versions if v.project_id == project.id), key=lambda v: v.number
        )
        result[project.id] = (
            len(sources),
            any(s.active and s.status is not SourceStatus.FAILED for s in sources),
            sum(q.status is QuestionStatus.OPEN for q in questions),
            sum(q.status is QuestionStatus.RESOLVED for q in questions),
            len(versions),
            tuple(versions[-1].lanes) if versions else (),
        )
    return result


def _shape(stats):
    return {
        pid: (
            s.sources,
            s.has_material,
            s.questions_open,
            s.questions_resolved,
            s.versions,
            s.lanes,
        )
        for pid, s in stats.items()
    }


@pytest.mark.asyncio
async def test_memory_stats_match_seed_and_default_to_zero():
    seed = build_seed()
    store = InMemoryStore()
    store.load(
        projects=seed.projects,
        sources=seed.sources,
        questions=seed.questions,
        runs=seed.runs,
        versions=seed.versions,
    )
    repo = store.repositories().projects
    stats = await repo.stats([p.id for p in seed.projects])
    assert _shape(stats) == _expected(seed)
    assert any(s.versions for s in stats.values())
    assert all(s.active_run_mode is None for s in stats.values()) or any(
        r.status in ACTIVE_STATUSES for r in seed.runs
    )
    assert await repo.stats([]) == {}


@pytest.mark.asyncio
async def test_sql_stats_match_memory_and_query_count_is_constant(sql_store):  # noqa: F811
    store, sessions = sql_store
    database = Database(os.environ["TEST_DATABASE_URL"])
    database.store = store
    database.sessions = sessions
    try:
        await database.seed(build_seed)
    finally:
        await database.dispose()
    seed = build_seed()
    assert isinstance(store, SqlStore)
    repo = store.repositories().projects
    ids = [p.id for p in seed.projects]
    assert len(ids) >= 3
    assert _shape(await repo.stats(ids)) == _expected(seed)

    statements: list[str] = []
    engine = sessions.kw["bind"].sync_engine

    def count(_conn, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        await repo.stats(ids[:1])
        one = len(statements)
        statements.clear()
        await repo.stats(ids)
        many = len(statements)
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert one == many
