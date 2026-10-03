"""Связать ответ вопроса с источником-основанием.

Revision ID: 0002_answer_source_fk
Revises: 0001_persistence
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_answer_source_fk"
down_revision = "0001_persistence"
branch_labels = None
depends_on = None

CONSTRAINT_NAME = "fk_questions_answer_source_id_sources"


def upgrade() -> None:
    bind = op.get_bind()
    foreign_keys = sa.inspect(bind).get_foreign_keys("questions")
    if not any(foreign_key["name"] == CONSTRAINT_NAME for foreign_key in foreign_keys):
        op.create_foreign_key(
            CONSTRAINT_NAME,
            "questions",
            "sources",
            ["answer_source_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    bind = op.get_bind()
    foreign_keys = sa.inspect(bind).get_foreign_keys("questions")
    if any(foreign_key["name"] == CONSTRAINT_NAME for foreign_key in foreign_keys):
        op.drop_constraint(CONSTRAINT_NAME, "questions", type_="foreignkey")
