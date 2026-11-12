"""Протокол совместимого сервера у ключа модели (ADR-0013).

`wire_api` — `chat_completions` или `responses`: шлюзы подписки ChatGPT (OpenAI Buffet) и
новые серверы OpenAI понимают только Responses API. Задаётся только у `openai_compatible`;
`NULL` у старых строк и остальных провайдеров означает Chat Completions, как раньше.

Revision ID: 0027_credential_wire_api
Revises: 0026_agent_search_limit
"""

import sqlalchemy as sa
from alembic import op

revision = "0027_credential_wire_api"
down_revision = "0026_agent_search_limit"
branch_labels = None
depends_on = None

CONSTRAINT = "ck_user_credentials_wire_api"


def upgrade() -> None:
    op.add_column("user_credentials", sa.Column("wire_api", sa.String(length=32), nullable=True))
    op.create_check_constraint(
        CONSTRAINT,
        "user_credentials",
        "wire_api IS NULL OR (provider = 'openai_compatible' "
        "AND wire_api IN ('chat_completions', 'responses'))",
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT, "user_credentials", type_="check")
    op.drop_column("user_credentials", "wire_api")
