"""Предупреждения о неполном чтении источника: страницы без текстового слоя и обрезанные листы."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013_source_read_warnings"
down_revision = "0012_deleted_project_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("warning", sa.Text(), nullable=True))
    op.add_column("sources", sa.Column("unreadable_pages", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("sources", "unreadable_pages")
    op.drop_column("sources", "warning")
