"""Полнотекстовый поиск по источникам для агентного режима (RFC-0004, инструмент search_sources).

Агент ищет нужный фрагмент длинного регламента или расшифровки, не читая весь текст:
`search_sources(query)` идёт в PostgreSQL FTS с конфигурацией `russian`. Индекс — выражение
`to_tsvector('russian', title || ' ' || content)`; запрос репозитория повторяет это выражение
буквально, иначе планировщик не сопоставит условие с индексом. Без индекса поиск работает,
но читает таблицу целиком.

Revision ID: 0024_agent_search
Revises: 0022_merge_wave2_heads
"""

import sqlalchemy as sa
from alembic import op

revision = "0024_agent_search"
down_revision = "0022_merge_wave2_heads"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_sources_fts_russian"
VECTOR_EXPRESSION = "to_tsvector('russian', title || ' ' || content)"


def upgrade() -> None:
    op.create_index(
        INDEX_NAME,
        "sources",
        [sa.text(VECTOR_EXPRESSION)],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="sources")
