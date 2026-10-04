"""Автор прогона и сохранённой версии для истории совместной работы.

Revision ID: 0008_version_actor
Revises: 0007_run_warnings
"""

import sqlalchemy as sa
from alembic import op

revision = "0008_version_actor"
down_revision = "0007_run_warnings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Старые версии остаются с неизвестным автором: приписывать их владельцу нельзя.
    op.add_column("runs", sa.Column("actor_email", sa.String(length=320), nullable=True))
    op.add_column(
        "diagram_versions", sa.Column("actor_email", sa.String(length=320), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("diagram_versions", "actor_email")
    op.drop_column("runs", "actor_email")
