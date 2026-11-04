"""Сессии правок и контрольные точки версий (ADR-0010)."""

import sqlalchemy as sa
from alembic import op

revision = "0015_version_sessions"
down_revision = "0014_user_llm_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("diagram_versions", sa.Column("label", sa.String(120), nullable=True))
    op.add_column(
        "diagram_versions",
        sa.Column("checkpoint", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("diagram_versions", sa.Column("session_started_at", sa.DateTime(timezone=True)))
    op.add_column("diagram_versions", sa.Column("updated_at", sa.DateTime(timezone=True)))
    op.add_column(
        "diagram_versions",
        sa.Column("saved_count", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column(
        "diagram_versions",
        sa.Column("trace_inherited", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "diagram_versions",
        sa.Column("report_inherited", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "diagram_versions",
        sa.Column("lint_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "diagram_versions",
        sa.Column("assumption_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.execute(
        "UPDATE diagram_versions SET "
        "lint_count = jsonb_array_length(COALESCE(report->'lint', '[]'::jsonb)), "
        "assumption_count = jsonb_array_length(COALESCE(report->'assumptions', '[]'::jsonb))"
    )
    # Старые версии — отдельные закрытые сессии: поведение истории не меняется.
    op.execute(
        "UPDATE diagram_versions SET session_started_at = created_at, updated_at = created_at"
    )


def downgrade() -> None:
    for column in (
        "assumption_count",
        "lint_count",
        "report_inherited",
        "trace_inherited",
        "saved_count",
        "updated_at",
        "session_started_at",
        "checkpoint",
        "label",
    ):
        op.drop_column("diagram_versions", column)
