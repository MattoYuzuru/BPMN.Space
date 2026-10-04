"""Онбординг: состояние тура, отмеченные пункты чек-листа и автор прогона.

Revision ID: 0008_onboarding
Revises: 0007_run_warnings
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_onboarding"
down_revision = "0007_run_warnings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_onboarding",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tour_status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("tour_step", sa.String(length=64), nullable=True),
        sa.Column("tour_project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("checklist_hidden", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tour_project_id"],
            ["projects.id"],
            name="fk_user_onboarding_tour_project",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "tour_status IN ('pending', 'active', 'completed', 'dismissed')",
            name="ck_user_onboarding_tour_status",
        ),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "user_onboarding_items",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_key", sa.String(length=64), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "source IN ('server', 'client')", name="ck_user_onboarding_items_source"
        ),
        sa.PrimaryKeyConstraint("user_id", "item_key"),
    )
    op.add_column("runs", sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_runs_created_by_users", "runs", "users", ["created_by"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint("fk_runs_created_by_users", "runs", type_="foreignkey")
    op.drop_column("runs", "created_by")
    op.drop_table("user_onboarding_items")
    op.drop_table("user_onboarding")
