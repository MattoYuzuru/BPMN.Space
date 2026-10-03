"""Ограничить связи «ответ—источник» и «прогон—версия» до один-к-одному.

Revision ID: 0004_persistence_relationships
Revises: 0003_run_artifacts
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_persistence_relationships"
down_revision = "0003_run_artifacts"
branch_labels = None
depends_on = None

RUN_VERSION_FK = "fk_runs_version_id_diagram_versions"
QUESTION_ANSWER_UNIQUE = "uq_questions_answer_source_id"
VERSION_RUN_UNIQUE = "uq_versions_run_id"


def upgrade() -> None:
    bind = op.get_bind()
    orphaned_versions = bind.scalar(
        sa.text(
            "SELECT count(*) FROM runs r "
            "LEFT JOIN diagram_versions v ON v.id = r.version_id "
            "WHERE r.version_id IS NOT NULL AND v.id IS NULL"
        )
    )
    duplicate_answers = bind.scalar(
        sa.text(
            "SELECT count(*) FROM (SELECT answer_source_id FROM questions "
            "WHERE answer_source_id IS NOT NULL GROUP BY answer_source_id HAVING count(*) > 1) q"
        )
    )
    duplicate_run_versions = bind.scalar(
        sa.text(
            "SELECT count(*) FROM (SELECT run_id FROM diagram_versions "
            "WHERE run_id IS NOT NULL GROUP BY run_id HAVING count(*) > 1) v"
        )
    )
    if orphaned_versions or duplicate_answers or duplicate_run_versions:
        raise RuntimeError(
            "Нельзя применить миграцию связей: найдены осиротевшие или повторные ссылки. "
            "Сначала устраните конфликты данных."
        )

    foreign_keys = sa.inspect(bind).get_foreign_keys("runs")
    if not any(item["name"] == RUN_VERSION_FK for item in foreign_keys):
        op.create_foreign_key(
            RUN_VERSION_FK,
            "runs",
            "diagram_versions",
            ["version_id"],
            ["id"],
            ondelete="SET NULL",
        )

    question_constraints = sa.inspect(bind).get_unique_constraints("questions")
    if not any(item["name"] == QUESTION_ANSWER_UNIQUE for item in question_constraints):
        op.create_unique_constraint(QUESTION_ANSWER_UNIQUE, "questions", ["answer_source_id"])

    version_constraints = sa.inspect(bind).get_unique_constraints("diagram_versions")
    if not any(item["name"] == VERSION_RUN_UNIQUE for item in version_constraints):
        op.create_unique_constraint(VERSION_RUN_UNIQUE, "diagram_versions", ["run_id"])


def downgrade() -> None:
    bind = op.get_bind()
    version_constraints = sa.inspect(bind).get_unique_constraints("diagram_versions")
    if any(item["name"] == VERSION_RUN_UNIQUE for item in version_constraints):
        op.drop_constraint(VERSION_RUN_UNIQUE, "diagram_versions", type_="unique")

    question_constraints = sa.inspect(bind).get_unique_constraints("questions")
    if any(item["name"] == QUESTION_ANSWER_UNIQUE for item in question_constraints):
        op.drop_constraint(QUESTION_ANSWER_UNIQUE, "questions", type_="unique")

    foreign_keys = sa.inspect(bind).get_foreign_keys("runs")
    if any(item["name"] == RUN_VERSION_FK for item in foreign_keys):
        op.drop_constraint(RUN_VERSION_FK, "runs", type_="foreignkey")
