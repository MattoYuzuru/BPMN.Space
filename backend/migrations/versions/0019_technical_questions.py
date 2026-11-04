"""Технические вопросы и ожидание прогона (RFC-0006, шаг 2; RFC-0005, шаг 5).

Категория вопроса, действия технического вопроса и блокирующий флаг; активный прогон теперь
включает `waiting` — ожидание действия пользователя по блокирующему вопросу.

Revision ID: 0019_technical_questions
Revises: 0018_llm_call_cost
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0019_technical_questions"
down_revision = "0018_llm_call_cost"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "questions",
        sa.Column("category", sa.String(length=16), nullable=False, server_default="business"),
    )
    op.add_column(
        "questions",
        sa.Column(
            "actions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "questions",
        sa.Column("blocking", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_check_constraint(
        "ck_questions_category",
        "questions",
        "category IN ('business', 'technical')",
    )
    # Ожидание действия пользователя тоже занимает проект: второй прогон начинать нельзя.
    op.drop_index("uq_runs_active_project", table_name="runs")
    op.create_index(
        "uq_runs_active_project",
        "runs",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running', 'waiting')"),
    )


def downgrade() -> None:
    op.drop_index("uq_runs_active_project", table_name="runs")
    op.create_index(
        "uq_runs_active_project",
        "runs",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    op.drop_constraint("ck_questions_category", "questions", type_="check")
    op.drop_column("questions", "blocking")
    op.drop_column("questions", "actions")
    op.drop_column("questions", "category")
