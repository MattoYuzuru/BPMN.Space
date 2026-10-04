"""Объединить ветки миграций онбординга, доступа зрителей и истории версий.

Revision ID: 0010_merge_heads
Revises: 0008_onboarding, 0009_version_actor
"""

revision = "0010_merge_heads"
down_revision = ("0008_onboarding", "0009_version_actor")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
