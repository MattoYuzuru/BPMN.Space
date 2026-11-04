"""Ключи моделей пользователей: шифртекст, подсказка, модель по умолчанию (ADR-0011).

Revision ID: 0014_user_llm_credentials
Revises: 0013_source_read_warnings
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0014_user_llm_credentials"
down_revision = "0013_source_read_warnings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_llm_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=60), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=True),
        sa.Column("encrypted_key", sa.LargeBinary(), nullable=False),
        sa.Column("key_hint", sa.String(length=8), nullable=False),
        sa.Column("default_model", sa.String(length=128), nullable=True),
        sa.Column("is_default", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "provider IN ('anthropic', 'openai', 'openai_compatible')",
            name="ck_user_llm_credentials_provider",
        ),
    )
    op.create_index("ix_user_llm_credentials_user_id", "user_llm_credentials", ["user_id"])
    op.create_index(
        "uq_user_llm_credentials_default",
        "user_llm_credentials",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )


def downgrade() -> None:
    op.drop_index("uq_user_llm_credentials_default", table_name="user_llm_credentials")
    op.drop_index("ix_user_llm_credentials_user_id", table_name="user_llm_credentials")
    op.drop_table("user_llm_credentials")
