"""Провенанс ответа, записанного внешним агентом (RFC-0007, шаг 2).

`answer_via=agent` — ответ пришёл по MCP через персональный токен владельца;
`answer_via_name` — название этого токена («Claude Code на ноутбуке»). Пусто — ответ
записал человек в интерфейсе, как раньше.

Revision ID: 0021_agent_answer_provenance
Revises: 0017_api_tokens
"""

import sqlalchemy as sa
from alembic import op

revision = "0021_agent_answer_provenance"
down_revision = "0017_api_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("questions", sa.Column("answer_via", sa.String(length=32), nullable=True))
    op.add_column("questions", sa.Column("answer_via_name", sa.String(length=80), nullable=True))


def downgrade() -> None:
    op.drop_column("questions", "answer_via_name")
    op.drop_column("questions", "answer_via")
