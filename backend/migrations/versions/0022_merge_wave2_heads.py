"""Объединить головы волны 2: стоимость, технические вопросы, ключи и провенанс ответа агента.

Revision ID: 0022_merge_wave2_heads
Revises: 0020_user_credentials, 0021_agent_answer_provenance

Финальная merge-ревизия волны 2: `0018`→`0019`→`0020` (стоимость, технические вопросы,
ключи) и ветка `0021` (провенанс ответа агента) сводятся к одной голове схемы.
"""

revision = "0022_merge_wave2_heads"
down_revision = ("0020_user_credentials", "0021_agent_answer_provenance")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
