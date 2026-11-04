"""Полнотекстовый поиск источников в PostgreSQL для агентного режима (RFC-0004).

Нужен `TEST_DATABASE_URL` (см. `make test-postgres`), иначе тест пропускается. Проверяются
миграция `0024_agent_search` (GIN-индекс по `to_tsvector('russian', title || ' ' || content)`)
и контракт репозитория: русская морфология, только читаемые моделью источники, лимит выдачи.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.domain.models import Project, Source, SourceKind, SourceStatus, SourceTrust
from tests.test_persistence import sql_test_store

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def _source(project_id, title: str, content: str, **overrides) -> Source:
    values = {
        "id": uuid4(),
        "project_id": project_id,
        "kind": SourceKind.TEXT,
        "title": title,
        "content": content,
        "status": SourceStatus.READY,
        "active": True,
        "created_at": NOW,
    }
    values.update(overrides)
    return Source(**values)


async def test_postgres_fts_search_uses_russian_morphology_and_migration_index() -> None:
    async with sql_test_store() as (store, sessions):
        repos = store.repositories()
        project_id = uuid4()
        await repos.projects.add(
            Project(
                id=project_id,
                title="Согласование",
                description=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        regulation = _source(
            project_id,
            "Регламент",
            "Инженер готовит акт и отправляет документы на согласование руководителю.",
        )
        invoice = _source(
            project_id,
            "Памятка",
            "Оператор проверяет заявки и возвращает неполные комплекты.",
        )
        inactive = _source(
            project_id,
            "Старое",
            "Заявки согласовывались по старой схеме.",
            active=False,
        )
        summary = _source(
            project_id,
            "Краткое содержание",
            "Согласование заявок в одном абзаце.",
            trust=SourceTrust.SUMMARY,
        )
        for source in (regulation, invoice, inactive, summary):
            await repos.sources.add(source)

        hits = await repos.sources.search(project_id, "согласование", limit=5)
        assert [hit.source_id for hit in hits] == [regulation.id]
        assert "согласование" in hits[0].snippet.lower()
        assert hits[0].rank > 0

        # Морфология russian: запрос «заявка» находит «заявки».
        morphology = await repos.sources.search(project_id, "заявка", limit=5)
        assert [hit.source_id for hit in morphology] == [invoice.id]

        # Выключенные и краткие содержания моделью не читаются и не находятся.
        assert await repos.sources.search(project_id, "согласовались", limit=5) == []
        assert await repos.sources.search(project_id, "абзаце", limit=5) == []
        assert await repos.sources.search(project_id, "заявки", limit=1) == [morphology[0]]
        assert await repos.sources.search(project_id, "  ", limit=5) == []

        async with sessions() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE schemaname = current_schema() "
                        "AND indexname = 'ix_sources_fts_russian'"
                    )
                )
            ).all()
        assert [row[0] for row in rows] == ["ix_sources_fts_russian"]
