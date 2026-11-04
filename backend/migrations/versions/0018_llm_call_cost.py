"""Кеш-токены и стоимость вызова модели (RFC-0005, шаг 4).

Revision ID: 0018_llm_call_cost
Revises: 0017_api_tokens
"""

import sqlalchemy as sa
from alembic import op

revision = "0018_llm_call_cost"
down_revision = "0017_api_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("llm_calls", sa.Column("cache_read_tokens", sa.Integer(), nullable=True))
    op.add_column("llm_calls", sa.Column("cache_write_tokens", sa.Integer(), nullable=True))
    op.add_column("llm_calls", sa.Column("cost_usd", sa.Numeric(14, 6), nullable=True))
    op.add_column("llm_calls", sa.Column("price_checked_on", sa.Date(), nullable=True))
    op.add_column("llm_calls", sa.Column("model", sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column("llm_calls", "model")
    op.drop_column("llm_calls", "price_checked_on")
    op.drop_column("llm_calls", "cost_usd")
    op.drop_column("llm_calls", "cache_write_tokens")
    op.drop_column("llm_calls", "cache_read_tokens")
