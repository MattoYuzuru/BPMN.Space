"""Предупреждения прогона (например, обрезанный контекст модели).

Revision ID: 0007_run_warnings
Revises: 0006_public_only_demo_projects
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_run_warnings"
down_revision = "0006_public_only_demo_projects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column(
            "warnings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("runs", "warnings")
