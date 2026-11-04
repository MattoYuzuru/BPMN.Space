"""Ограничить индексируемый текст FTS-поиска агентного режима (RFC-0004).

`tsvector` PostgreSQL не принимает больше 1 МБ, а текст источника бывает до миллиона знаков:
`to_tsvector('russian', title || ' ' || content)` на таком документе падает. Поиск агента
(`search_sources`) индексирует название и первые 100 тыс. знаков; хвост длинного документа
читают `read_source` по оглавлению. Индекс из `0024_agent_search` пересоздаётся с тем же
именем: запрос репозитория повторяет новое выражение буквально, иначе планировщик не
сопоставит условие с индексом.

Revision ID: 0026_agent_search_limit
Revises: 0025_merge_wave4_heads
"""

import sqlalchemy as sa
from alembic import op

revision = "0026_agent_search_limit"
down_revision = "0025_merge_wave4_heads"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_sources_fts_russian"
# Предел индексируемого текста: tsvector PostgreSQL ограничен 1 МБ.
FTS_INDEXED_CHARS = 100_000
OLD_EXPRESSION = "to_tsvector('russian', title || ' ' || content)"
NEW_EXPRESSION = f"to_tsvector('russian', left(title || ' ' || content, {FTS_INDEXED_CHARS}))"


def upgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="sources")
    op.create_index(
        INDEX_NAME,
        "sources",
        [sa.text(NEW_EXPRESSION)],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="sources")
    op.create_index(
        INDEX_NAME,
        "sources",
        [sa.text(OLD_EXPRESSION)],
        postgresql_using="gin",
    )
