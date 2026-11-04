"""Производные источники и дерево материалов (RFC-0006, шаг 3).

Новые поля `sources`: `origin`, `parent_id` (родитель того же проекта, каскадное удаление),
`derivation`, `trust`, `edited_by_human`, `media`. Существующие ответы на вопросы получают
`origin=answer`, прочие — `origin=user`; все — `trust=primary`. Старые записи с
расшифровкой в самом источнике остаются одним узлом: текст и цитаты не переезжают.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016_source_derivation"
down_revision = "0015_version_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column("origin", sa.String(16), nullable=False, server_default="user"),
    )
    op.add_column("sources", sa.Column("parent_id", sa.Uuid(), nullable=True))
    op.add_column("sources", sa.Column("derivation", postgresql.JSONB(), nullable=True))
    op.add_column(
        "sources",
        sa.Column("trust", sa.String(16), nullable=False, server_default="primary"),
    )
    op.add_column(
        "sources",
        sa.Column("edited_by_human", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("sources", sa.Column("media", postgresql.JSONB(), nullable=True))
    op.execute("UPDATE sources SET origin = 'answer' WHERE kind = 'answer'")
    op.create_unique_constraint("uq_sources_id_project", "sources", ["id", "project_id"])
    op.create_foreign_key(
        "fk_sources_parent_same_project",
        "sources",
        "sources",
        ["parent_id", "project_id"],
        ["id", "project_id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_sources_parent_id", "sources", ["parent_id"])
    op.create_check_constraint(
        "ck_sources_origin",
        "sources",
        "origin IN ('user', 'derived', 'agent', 'answer')",
    )
    op.create_check_constraint(
        "ck_sources_trust",
        "sources",
        "trust IN ('primary', 'extracted', 'observed', 'external', 'agent', 'summary')",
    )
    op.create_check_constraint("ck_sources_not_own_parent", "sources", "parent_id <> id")


def downgrade() -> None:
    # Производные источники без родительской модели не имеют смысла: удаляются вместе с полями.
    op.execute("DELETE FROM sources WHERE parent_id IS NOT NULL")
    op.drop_constraint("ck_sources_not_own_parent", "sources", type_="check")
    op.drop_constraint("ck_sources_trust", "sources", type_="check")
    op.drop_constraint("ck_sources_origin", "sources", type_="check")
    op.drop_index("ix_sources_parent_id", table_name="sources")
    op.drop_constraint("fk_sources_parent_same_project", "sources", type_="foreignkey")
    op.drop_constraint("uq_sources_id_project", "sources", type_="unique")
    for column in ("media", "edited_by_human", "trust", "derivation", "parent_id", "origin"):
        op.drop_column("sources", column)
