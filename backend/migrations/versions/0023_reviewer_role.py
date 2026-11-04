"""Роль ссылки reviewer и область проверки (RFC-0007, шаг 3).

Что меняется:

- `project_share_links.role` расширяется до `viewer | editor | reviewer`; старые ссылки не
  ломаются, CHECK пересоздаётся после проверки существующих значений.
- `project_share_links.lane_ids` — область проверки: id дорожек BPMN (пусто — весь проект).
- `api_tokens.share_link_id` и `api_tokens.lane_ids` — токен агента, выданный по ссылке
  проверки: он живёт областью ссылки, а ссылка проверяется при каждом запросе.
- `questions.answer_share_link_id` — провенанс ответа, данного по ссылке проверки.

Revision ID: 0023_reviewer_role
Revises: 0022_merge_wave2_heads
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0023_reviewer_role"
down_revision = "0022_merge_wave2_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Роль ссылки: безопасное расширение CHECK (сначала отдаём старую проверку, потом новую).
    op.drop_constraint("ck_project_share_links_role", "project_share_links", type_="check")
    op.create_check_constraint(
        "ck_project_share_links_role",
        "project_share_links",
        "role IN ('viewer', 'editor', 'reviewer')",
    )
    op.add_column(
        "project_share_links",
        sa.Column(
            "lane_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )

    # Токен проверки: ссылка, по которой выдан, и её область.
    op.add_column(
        "api_tokens",
        sa.Column("share_link_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_api_tokens_share_link_id",
        "api_tokens",
        "project_share_links",
        ["share_link_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_api_tokens_share_link_id", "api_tokens", ["share_link_id"])
    op.add_column(
        "api_tokens",
        sa.Column("lane_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    # Провенанс ответа по ссылке проверки.
    op.add_column(
        "questions",
        sa.Column("answer_share_link_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_questions_answer_share_link_id",
        "questions",
        "project_share_links",
        ["answer_share_link_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_questions_answer_share_link_id", "questions", ["answer_share_link_id"])


def downgrade() -> None:
    op.drop_constraint("fk_questions_answer_share_link_id", "questions", type_="foreignkey")
    op.drop_column("questions", "answer_share_link_id")
    op.drop_constraint("fk_api_tokens_share_link_id", "api_tokens", type_="foreignkey")
    op.drop_column("api_tokens", "lane_ids")
    op.drop_column("api_tokens", "share_link_id")
    op.drop_column("project_share_links", "lane_ids")
    # Откат роли: ссылки проверки становятся ссылками просмотра, чтобы CHECK не упал на данных.
    # Важно не расширить доступ: без revoked_at бывшая проверка (область-дорожки) стала бы
    # ссылкой просмотра на весь проект. Поэтому гасим такие ссылки, а не понижаем молча.
    op.execute(
        "UPDATE project_share_links SET role = 'viewer', "
        "revoked_at = COALESCE(revoked_at, now()) WHERE role = 'reviewer'"
    )
    op.drop_constraint("ck_project_share_links_role", "project_share_links", type_="check")
    op.create_check_constraint(
        "ck_project_share_links_role", "project_share_links", "role IN ('viewer', 'editor')"
    )
