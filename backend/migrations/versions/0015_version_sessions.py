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


_BATCH = 200


def _materialize(column: str, flag: str, default: str) -> None:
    """Вернуть унаследованные цитаты/отчёт в строки: старый код читает их только из строки.

    Владелец — ближайшая более ранняя версия проекта с `flag = false` (как в
    `SqlVersionRepository._metadata`); владельцы не меняются, поэтому порядок пакетов не важен.
    """
    bind = op.get_bind()
    statement = sa.text(
        f"UPDATE diagram_versions AS v SET {column} = COALESCE(("  # noqa: S608 — константы
        f"SELECT o.{column} FROM diagram_versions o "
        f"WHERE o.project_id = v.project_id AND o.number < v.number AND o.{flag} = false "
        f"ORDER BY o.number DESC LIMIT 1), CAST(:default AS jsonb)), {flag} = false "
        f"WHERE v.id IN (SELECT id FROM diagram_versions WHERE {flag} = true LIMIT :batch)"
    )
    while bind.execute(statement, {"default": default, "batch": _BATCH}).rowcount:
        pass


def downgrade() -> None:
    _materialize("trace", "trace_inherited", "{}")
    _materialize(
        "report", "report_inherited", '{"xsd_valid": false, "lint": [], "assumptions": []}'
    )
    # Отложенные проверки после UPDATE блокируют ALTER TABLE в той же транзакции.
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")
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
