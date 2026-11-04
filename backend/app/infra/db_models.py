"""Реляционная схема хранения (RFC §5.7)."""

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTableUUID
from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyBaseAccessTokenTableUUID
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import (
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


class Base(DeclarativeBase):
    pass


class UserRow(SQLAlchemyBaseUserTableUUID, Base):
    """Учётная запись; пароли хеширует FastAPI Users с Argon2."""

    __tablename__ = "users"


class AccessTokenRow(SQLAlchemyBaseAccessTokenTableUUID, Base):
    """Отзываемая серверная сессия пользователя."""

    __tablename__ = "access_tokens"

    if TYPE_CHECKING:
        token: str
        user_id: UUID
    else:

        @declared_attr
        def user_id(cls) -> Mapped[UUID]:  # noqa: N805 - SQLAlchemy declared_attr uses cls
            return mapped_column(
                Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
            )


class ProjectRow(Base):
    __tablename__ = "projects"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    owner_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_projects_owner_id_users"),
        index=True,
    )
    public_read_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sql_text("false")
    )


class ProjectMemberRow(Base):
    __tablename__ = "project_members"
    __table_args__ = (
        CheckConstraint("role IN ('viewer', 'editor')", name="ck_project_members_role"),
    )
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="editor")
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProjectShareLinkRow(Base):
    __tablename__ = "project_share_links"
    __table_args__ = (
        CheckConstraint("role IN ('viewer', 'editor')", name="ck_project_share_links_role"),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > created_at",
            name="ck_project_share_links_expiry",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourceRow(Base):
    __tablename__ = "sources"
    __table_args__ = (
        # Родитель — источник того же проекта; удаление родителя удаляет производные (RFC-0006).
        UniqueConstraint("id", "project_id", name="uq_sources_id_project"),
        ForeignKeyConstraint(
            ["parent_id", "project_id"],
            ["sources.id", "sources.project_id"],
            name="fk_sources_parent_same_project",
            ondelete="CASCADE",
        ),
        Index("ix_sources_parent_id", "parent_id"),
        CheckConstraint(
            "origin IN ('user', 'derived', 'agent', 'answer')", name="ck_sources_origin"
        ),
        CheckConstraint(
            "trust IN ('primary', 'extracted', 'observed', 'external', 'agent', 'summary')",
            name="ck_sources_trust",
        ),
        CheckConstraint("parent_id <> id", name="ck_sources_not_own_parent"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    file_name: Mapped[str | None] = mapped_column(String(500))
    mime: Mapped[str | None] = mapped_column(String(255))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    duration_sec: Mapped[float | None] = mapped_column(Float)
    question_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), index=True)
    error: Mapped[str | None] = mapped_column(Text)
    file_key: Mapped[str | None] = mapped_column(String(1024))
    digest: Mapped[str | None] = mapped_column(Text)
    warning: Mapped[str | None] = mapped_column(Text)
    unreadable_pages: Mapped[list[int] | None] = mapped_column(JSONB)
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    parent_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    derivation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    trust: Mapped[str] = mapped_column(String(16), nullable=False, default="primary")
    edited_by_human: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    media: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class RunRow(Base):
    __tablename__ = "runs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mode: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stage: Mapped[str | None] = mapped_column(String(32))
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[dict[str, Any] | None] = mapped_column("questions_summary", JSONB)
    analysis: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ir: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    model: Mapped[str | None] = mapped_column(String(128))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    actor_email: Mapped[str | None] = mapped_column(String(320))
    version_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "diagram_versions.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_runs_version_id_diagram_versions",
        ),
    )
    error: Mapped[str | None] = mapped_column(Text)
    warnings: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=sql_text("'[]'::jsonb")
    )
    created_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_runs_created_by_users"),
    )


class UserOnboardingRow(Base):
    """Состояние тура и чек-листа пользователя; создаётся лениво при первом обращении."""

    __tablename__ = "user_onboarding"
    __table_args__ = (
        CheckConstraint(
            "tour_status IN ('pending', 'active', 'completed', 'dismissed')",
            name="ck_user_onboarding_tour_status",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    tour_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    tour_step: Mapped[str | None] = mapped_column(String(64))
    tour_project_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("projects.id", ondelete="SET NULL", name="fk_user_onboarding_tour_project"),
    )
    checklist_hidden: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sql_text("false")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UserOnboardingItemRow(Base):
    """Отмеченный пункт чек-листа; ключ — значение `ChecklistItem` (новые пункты без миграций)."""

    __tablename__ = "user_onboarding_items"
    __table_args__ = (
        CheckConstraint("source IN ('server', 'client')", name="ck_user_onboarding_items_source"),
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    item_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)


class QuestionRow(Base):
    __tablename__ = "questions"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_questions_project_code"),
        UniqueConstraint("answer_source_id", name="uq_questions_answer_source_id"),
        CheckConstraint("category IN ('business', 'technical')", name="ck_questions_category"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    assumption: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    about: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    element_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    answer_source_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sources.id", ondelete="SET NULL")
    )
    answer_text: Mapped[str | None] = mapped_column(Text)
    # Провенанс ответа (RFC-0007): `agent` — ответ записал внешний агент владельца токена.
    answer_via: Mapped[str | None] = mapped_column(String(32))
    answer_via_name: Mapped[str | None] = mapped_column(String(80))
    run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("runs.id", ondelete="SET NULL")
    )
    # RFC-0006, шаг 2: категория вопроса, действия технического вопроса и блокирующий флаг.
    category: Mapped[str] = mapped_column(
        String(16), nullable=False, default="business", server_default="business"
    )
    actions: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=sql_text("'[]'::jsonb")
    )
    blocking: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("false")
    )


class DiagramVersionRow(Base):
    __tablename__ = "diagram_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "number", name="uq_versions_project_number"),
        UniqueConstraint("run_id", name="uq_versions_run_id"),
        CheckConstraint("storage_depth BETWEEN 0 AND 20", name="ck_versions_storage_depth"),
        CheckConstraint(
            "(bpmn_xml IS NOT NULL AND packed_xml IS NULL AND xml_sha256 IS NULL "
            "AND base_version_id IS NULL AND storage_depth = 0) OR "
            "(bpmn_xml IS NULL AND packed_xml IS NOT NULL AND xml_sha256 IS NOT NULL AND "
            "((base_version_id IS NULL AND storage_depth = 0) OR "
            "(base_version_id IS NOT NULL AND storage_depth > 0)))",
            name="ck_versions_storage_format",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    origin: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_email: Mapped[str | None] = mapped_column(String(320))
    bpmn_xml: Mapped[str | None] = mapped_column(Text)
    packed_xml: Mapped[bytes | None] = mapped_column(LargeBinary)
    xml_sha256: Mapped[str | None] = mapped_column(String(64))
    base_version_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("diagram_versions.id", deferrable=True, initially="DEFERRED"),
        index=True,
    )
    storage_depth: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    diff: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    trace: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    lanes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("runs.id", ondelete="SET NULL")
    )
    # ADR-0010: сессии правок и контрольные точки.
    label: Mapped[str | None] = mapped_column(String(120))
    checkpoint: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sql_text("false")
    )
    session_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    saved_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=sql_text("1")
    )
    # Цитаты не изменились с прошлой версии: `trace` пуст, читаются у ближайшего владельца.
    trace_inherited: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sql_text("false")
    )
    # То же для отчёта; счётчики хранятся отдельно, чтобы список истории не читал JSONB.
    report_inherited: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sql_text("false")
    )
    lint_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=sql_text("0")
    )
    assumption_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=sql_text("0")
    )


class UserLlmCredentialRow(Base):
    """Ключ модели пользователя; открытого ключа нет — только шифртекст и подсказка."""

    __tablename__ = "user_llm_credentials"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('anthropic', 'openai', 'openai_compatible')",
            name="ck_user_llm_credentials_provider",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(60), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(500))
    encrypted_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_hint: Mapped[str] = mapped_column(String(8), nullable=False)
    default_model: Mapped[str | None] = mapped_column(String(128))
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sql_text("false")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))


class ApiTokenRow(Base):
    """Персональный токен доступа для агентов (RFC-0007): только SHA-256 секрета и префикс."""

    __tablename__ = "api_tokens"
    __table_args__ = (
        CheckConstraint("cardinality(scopes) > 0", name="ck_api_tokens_scopes_not_empty"),
        CheckConstraint(
            "scopes <@ ARRAY['projects:read', 'projects:write', 'sources:write', "
            "'sources:delete', 'runs:start', 'questions:answer']::varchar[]",
            name="ck_api_tokens_scopes_known",
        ),
        CheckConstraint("expires_at > created_at", name="ck_api_tokens_expiry"),
        UniqueConstraint("token_hash", name="uq_api_tokens_token_hash"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    token_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String(32)), nullable=False)
    # NULL — все проекты пользователя.
    project_ids: Mapped[list[UUID] | None] = mapped_column(ARRAY(Uuid(as_uuid=True)))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LlmCallRow(Base):
    __tablename__ = "llm_calls"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    request: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    response: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    # Кеш и стоимость по ценам справочника на момент вызова (RFC-0005, шаг 4).
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer)
    cache_write_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(14, 6))
    price_checked_on: Mapped[date | None] = mapped_column(Date)
    model: Mapped[str | None] = mapped_column(String(128))
    latency_ms: Mapped[int | None] = mapped_column(Integer)


Index(
    "uq_runs_active_project",
    RunRow.project_id,
    unique=True,
    postgresql_where=sql_text("status IN ('queued', 'running', 'waiting')"),
)


Index(
    "uq_user_llm_credentials_default",
    UserLlmCredentialRow.user_id,
    unique=True,
    postgresql_where=sql_text("is_default"),
)


class DeletedProjectAccessRow(Base):
    """Короткая квитанция удаления; содержимого проекта и идентификаторов людей нет."""

    __tablename__ = "deleted_project_access"
    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
