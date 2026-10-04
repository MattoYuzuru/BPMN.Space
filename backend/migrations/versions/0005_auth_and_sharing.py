"""Пользователи, серверные сессии, участники проектов и ссылки доступа.

Revision ID: 0005_auth_and_sharing
Revises: 0004_persistence_relationships
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_auth_and_sharing"
down_revision = "0004_persistence_relationships"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=1024), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_superuser", sa.Boolean(), nullable=False),
        sa.Column("is_verified", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_table(
        "access_tokens",
        sa.Column("token", sa.String(length=43), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("token"),
    )
    op.create_index("ix_access_tokens_created_at", "access_tokens", ["created_at"], unique=False)
    op.add_column("projects", sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(
        "projects",
        sa.Column("public_read_only", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_foreign_key(
        "fk_projects_owner_id_users", "projects", "users", ["owner_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_projects_owner_id", "projects", ["owner_id"], unique=False)
    op.create_table(
        "project_members",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint("role = 'editor'", name="ck_project_members_role"),
        sa.PrimaryKeyConstraint("project_id", "user_id"),
    )
    op.create_table(
        "project_share_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint("role IN ('viewer', 'editor')", name="ck_project_share_links_role"),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > created_at",
            name="ck_project_share_links_expiry",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_project_share_links_project_id", "project_share_links", ["project_id"])
    op.create_index(
        "ix_project_share_links_token_hash", "project_share_links", ["token_hash"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_project_share_links_token_hash", table_name="project_share_links")
    op.drop_index("ix_project_share_links_project_id", table_name="project_share_links")
    op.drop_table("project_share_links")
    op.drop_table("project_members")
    op.drop_index("ix_projects_owner_id", table_name="projects")
    op.drop_constraint("fk_projects_owner_id_users", "projects", type_="foreignkey")
    op.drop_column("projects", "public_read_only")
    op.drop_column("projects", "owner_id")
    op.drop_index("ix_access_tokens_created_at", table_name="access_tokens")
    op.drop_table("access_tokens")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
