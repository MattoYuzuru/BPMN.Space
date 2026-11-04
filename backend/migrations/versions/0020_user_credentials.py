"""Ключи пользователей по типам задач (RFC-0006): user_llm_credentials → user_credentials.

Одна строка закрывает одну или несколько возможностей (`kinds`): LLM, распознавание речи,
OCR, vision, видео, поиск и чтение страниц, TTS. Шифрование Fernet и привязка шифртекста к
пользователю остаются как в ADR-0011: перешифровывать ничего не нужно, столбцы совместимы.

Существующие ключи моделей переносятся без потери данных (`kinds = {llm}`, приоритет 100,
включены, отметки использования и ошибки сохраняются). Старая таблица `user_llm_credentials`
**не удаляется в этом релизе**: она остаётся legacy-копией, чтобы откат только кода
(scripts/deploy.sh переключает релиз, но не схему) запускал старый код без
`relation "user_llm_credentials" does not exist`. Удалить её отдельной миграцией можно
только в следующем релизе, когда откат к коду до волны 2 уже не поддерживается.

Откат (`downgrade`) переносит ключи типа `llm`, созданные после релиза, обратно в
legacy-таблицу и удаляет `user_credentials`. Ключи инструментов (не-LLM) в прежней схеме не
представлены и при откате теряются — это фиксируется в docs/deployment.md.

Revision ID: 0020_user_credentials
Revises: 0019_technical_questions
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0020_user_credentials"
down_revision = "0019_technical_questions"
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
    # `user_llm_credentials` намеренно остаётся: это legacy-копия для отката только кода.
    # Удаление — отдельной миграцией в следующем релизе, когда такой откат не поддерживается.


def downgrade() -> None:
    # Возвращаем в legacy-таблицу ключи моделей, созданные/изменённые после релиза.
    op.execute(
        sa.text(
            "INSERT INTO user_llm_credentials (id, user_id, provider, label, base_url, "
            "encrypted_key, key_hint, default_model, is_default, created_at, last_used_at, "
            "last_error) "
            "SELECT id, user_id, provider, label, base_url, encrypted_key, key_hint, "
            "default_model, false, created_at, last_used_at, last_error "
            "FROM user_credentials WHERE kinds <@ ARRAY['llm']::varchar[] "
            "ON CONFLICT (id) DO NOTHING"
        )
    )
    # «По умолчанию» — не больше одного ключа на пользователя (частичный уникальный индекс).
    op.execute(
        sa.text(
            "UPDATE user_llm_credentials AS legacy SET is_default = true "
            "FROM user_credentials AS current "
            "WHERE legacy.id = current.id AND current.is_default "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM user_llm_credentials AS other "
            "  WHERE other.user_id = current.user_id AND other.is_default"
            ")"
        )
    )
    # Ключи инструментов (не-LLM) в прежней схеме не представлены: при откате теряются.
    op.drop_index("uq_user_credentials_default", table_name="user_credentials")
    op.drop_index("ix_user_credentials_user_priority", table_name="user_credentials")
    op.drop_index("ix_user_credentials_user_id", table_name="user_credentials")
    op.drop_table("user_credentials")
