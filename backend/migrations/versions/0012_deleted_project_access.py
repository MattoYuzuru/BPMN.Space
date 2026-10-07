"""Квитанции удаления для бывших участников и обладателей действовавших ссылок."""

import sqlalchemy as sa
from alembic import op

revision = "0012_deleted_project_access"
down_revision = "0011_compact_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deleted_project_access",
        sa.Column("key_hash", sa.String(64), primary_key=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_deleted_project_access_expires_at", "deleted_project_access", ["expires_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_deleted_project_access_expires_at", table_name="deleted_project_access")
    op.drop_table("deleted_project_access")
