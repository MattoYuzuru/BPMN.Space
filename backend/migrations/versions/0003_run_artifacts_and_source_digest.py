"""Сохранение снимков прогона и кэша дайджеста источника.

Revision ID: 0003_run_artifacts
Revises: 0002_answer_source_fk
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_run_artifacts"
down_revision = "0002_answer_source_fk"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    source_columns = _columns("sources")
    if "digest" not in source_columns:
        op.add_column("sources", sa.Column("digest", sa.Text(), nullable=True))

    run_columns = _columns("runs")
    if "summary" in run_columns and "questions_summary" not in run_columns:
        op.alter_column("runs", "summary", new_column_name="questions_summary")
        run_columns.remove("summary")
        run_columns.add("questions_summary")
    for name, column in (
        ("analysis", sa.Column("analysis", postgresql.JSONB(), nullable=True)),
        ("ir", sa.Column("ir", postgresql.JSONB(), nullable=True)),
        ("report", sa.Column("report", postgresql.JSONB(), nullable=True)),
        ("model", sa.Column("model", sa.String(length=128), nullable=True)),
        ("latency_ms", sa.Column("latency_ms", sa.Integer(), nullable=True)),
    ):
        if name not in run_columns:
            op.add_column("runs", column)


def downgrade() -> None:
    run_columns = _columns("runs")
    for name in ("latency_ms", "model", "report", "ir", "analysis"):
        if name in run_columns:
            op.drop_column("runs", name)
    if "questions_summary" in run_columns and "summary" not in run_columns:
        op.alter_column("runs", "questions_summary", new_column_name="summary")
    if "digest" in _columns("sources"):
        op.drop_column("sources", "digest")
