"""Разрешить сохранять в профиле принятые ссылки только на чтение.

Revision ID: 0008_viewer_memberships
Revises: 0007_run_warnings
"""

from alembic import op

revision = "0008_viewer_memberships"
down_revision = "0007_run_warnings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_project_members_role", "project_members", type_="check")
    op.create_check_constraint(
        "ck_project_members_role", "project_members", "role IN ('viewer', 'editor')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM project_members WHERE role = 'viewer'")
    op.drop_constraint("ck_project_members_role", "project_members", type_="check")
    op.create_check_constraint("ck_project_members_role", "project_members", "role = 'editor'")
