"""Объединить головы волны 2: стоимость прогона и провенанс ответа агента.

Revision ID: 0022_merge_wave2_heads
Revises: 0018_llm_call_cost, 0021_agent_answer_provenance

Заготовка интеграции: к финальному слиянию волны 2 добавятся `0019_technical_questions`
и `0020_user_credentials`, тогда merge-миграция пересоздаётся с полным списком голов
(`alembic merge`), чтобы в `main` у схемы осталась одна голова.
"""

revision = "0022_merge_wave2_heads"
down_revision = ("0018_llm_call_cost", "0021_agent_answer_provenance")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
