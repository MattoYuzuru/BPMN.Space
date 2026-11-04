"""Ключи пользователей по типам задач (RFC-0006): user_llm_credentials → user_credentials.

Одна строка закрывает одну или несколько возможностей (`kinds`): LLM, распознавание речи,
OCR, vision, видео, поиск и чтение страниц, TTS. Шифрование Fernet и привязка шифртекста к
пользователю остаются как в ADR-0011: перешифровывать ничего не нужно, столбцы совместимы.

Существующие ключи моделей переносятся без потери данных (`kinds = {llm}`, приоритет 100,
включены, отметки использования и ошибки сохраняются). Откат возвращает прежнюю таблицу
ключей моделей; ключи других типов при откате потерялись бы, поэтому downgrade честно
останавливается, пока они есть.

Revision ID: 0020_user_credentials
Revises: 0017_api_tokens
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0020_user_credentials"
down_revision = "0017_api_tokens"
branch_labels = None
depends_on = None

_KINDS = "'llm', 'speech_to_text', 'ocr', 'vision', 'video', 'web_search', 'web_fetch', 'tts'"


def upgrade() -> None:
    op.create_table(
        "user_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "kinds",
            postgresql.ARRAY(sa.String(length=32)),
            nullable=False,
            comment="Типы задач, которые закрывает ключ (RFC-0006)",
        ),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=60), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=True),
        sa.Column("encrypted_key", sa.LargeBinary(), nullable=False),
        sa.Column("key_hint", sa.String(length=8), nullable=False),
        sa.Column("default_model", sa.String(length=128), nullable=True),
        sa.Column("priority", sa.Integer(), server_default=sa.text("100"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("monthly_limit", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("exhausted_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=32), nullable=True),
        sa.Column("is_default", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint("cardinality(kinds) > 0", name="ck_user_credentials_kinds_not_empty"),
        sa.CheckConstraint(
            f"kinds <@ ARRAY[{_KINDS}]::varchar[]",
            name="ck_user_credentials_kinds_known",
        ),
        sa.CheckConstraint("priority >= 0", name="ck_user_credentials_priority"),
        sa.CheckConstraint(
            "last_error_code IS NULL OR last_error_code IN "
            "('transient', 'quota_exhausted', 'auth', 'unsupported', 'fatal')",
            name="ck_user_credentials_last_error_code",
        ),
    )
    op.create_index("ix_user_credentials_user_id", "user_credentials", ["user_id"])
    op.create_index(
        "ix_user_credentials_user_priority",
        "user_credentials",
        ["user_id", "priority", "created_at"],
    )
    op.create_index(
        "uq_user_credentials_default",
        "user_credentials",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    # Перенос ключей моделей: тип `llm`, приоритет по умолчанию (100), ключи включены.
    op.execute(
        sa.text(
            "INSERT INTO user_credentials (id, user_id, kinds, provider, label, base_url, "
            "encrypted_key, key_hint, default_model, priority, enabled, is_default, created_at, "
            "last_used_at, last_error) "
            "SELECT id, user_id, ARRAY['llm']::varchar[], provider, label, base_url, "
            "encrypted_key, key_hint, default_model, 100, true, is_default, created_at, "
            "last_used_at, last_error FROM user_llm_credentials"
        )
    )
    op.drop_index("uq_user_llm_credentials_default", table_name="user_llm_credentials")
    op.drop_index("ix_user_llm_credentials_user_id", table_name="user_llm_credentials")
    op.drop_table("user_llm_credentials")


def downgrade() -> None:
    bind = op.get_bind()
    # Ключи не-LLM типов в прежнюю схему не помещаются: откат не должен их молча терять.
    stray = bind.execute(
        sa.text(
            "SELECT count(*) FROM user_credentials WHERE NOT (kinds <@ ARRAY['llm']::varchar[])"
        )
    ).scalar_one()
    if stray:
        raise RuntimeError(
            "Откат 0020_user_credentials невозможен: есть ключи не-LLM типов ("
            f"{stray}). Удалите их в настройках или не откатывайтесь на схему без обобщённых "
            "ключей — иначе они пропадут"
        )
    op.create_table(
        "user_llm_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=60), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=True),
        sa.Column("encrypted_key", sa.LargeBinary(), nullable=False),
        sa.Column("key_hint", sa.String(length=8), nullable=False),
        sa.Column("default_model", sa.String(length=128), nullable=True),
        sa.Column("is_default", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "provider IN ('anthropic', 'openai', 'openai_compatible')",
            name="ck_user_llm_credentials_provider",
        ),
    )
    op.create_index("ix_user_llm_credentials_user_id", "user_llm_credentials", ["user_id"])
    op.create_index(
        "uq_user_llm_credentials_default",
        "user_llm_credentials",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    op.execute(
        sa.text(
            "INSERT INTO user_llm_credentials (id, user_id, provider, label, base_url, "
            "encrypted_key, key_hint, default_model, is_default, created_at, last_used_at, "
            "last_error) "
            "SELECT id, user_id, provider, label, base_url, encrypted_key, key_hint, "
            "default_model, is_default, created_at, last_used_at, last_error "
            "FROM user_credentials WHERE kinds <@ ARRAY['llm']::varchar[]"
        )
    )
    op.drop_index("uq_user_credentials_default", table_name="user_credentials")
    op.drop_index("ix_user_credentials_user_priority", table_name="user_credentials")
    op.drop_index("ix_user_credentials_user_id", table_name="user_credentials")
    op.drop_table("user_credentials")
