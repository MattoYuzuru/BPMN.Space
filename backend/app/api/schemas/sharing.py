"""Контракты доступа по ссылке и ролям проекта."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field, model_validator

from app.api.schemas.common import ApiModel
from app.api.schemas.projects import ProjectDetail


class ShareRole(StrEnum):
    VIEWER = "viewer"
    EDITOR = "editor"
    # Проверка коллегой (RFC-0007, шаг 3): область-дорожки, чтение и ответы на вопросы области.
    REVIEWER = "reviewer"


class ShareLinkCreate(ApiModel):
    role: ShareRole
    expires_in_days: int | None = Field(
        default=None,
        ge=0,
        le=365,
        description=(
            "Срок ссылки в днях: 7, 30, 365 (год) или 0 (без срока). Для совместимости "
            "null/пропуск выбирает 30 дней. Одинаковые варианты для viewer, editor и reviewer."
        ),
    )
    lane_ids: list[str] = Field(
        default_factory=list,
        max_length=30,
        description=(
            "Область проверки для role=reviewer: id дорожек схемы (допустимы и названия), "
            "пусто — весь проект. Для viewer/editor не задаётся"
        ),
    )

    @model_validator(mode="after")
    def only_reviewer_has_scope(self) -> "ShareLinkCreate":
        if self.role is not ShareRole.REVIEWER and self.lane_ids:
            raise ValueError("Область дорожек задаётся только для ссылки проверки")
        return self


class ReviewScope(ApiModel):
    """Область проверки: дорожки схемы, которые видит коллега."""

    lane_ids: list[str] = Field(default_factory=list)
    lanes: list[str] = Field(default_factory=list, description="Названия дорожек для интерфейса")
    whole_project: bool = Field(description="Пустая область — весь проект")


class ShareLinkCreated(ApiModel):
    id: UUID
    role: ShareRole
    url_path: str = Field(description="Одноразово возвращаемый путь с секретом ссылки")
    created_at: datetime
    expires_at: datetime | None
    lane_ids: list[str] = Field(default_factory=list)


class ShareLinkRead(ApiModel):
    id: UUID
    role: ShareRole
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    lane_ids: list[str] = Field(default_factory=list)


class SharedProject(ApiModel):
    role: ShareRole
    editor_requires_account: bool
    scope: ReviewScope
    detail: ProjectDetail


class ReviewQuestionRecap(ApiModel):
    """Вопрос области в готовом промпте: без ответов и внутренних полей."""

    id: UUID
    code: str
    text: str
    status: str
    severity: str
    element_ids: list[str] = Field(default_factory=list)


class AgentPrompt(ApiModel):
    """Готовый текст для агента проверяющего: без секрета ссылки и ключей."""

    text: str = Field(description="Готовый промпт «проверь дорожку» для вставки в агента")
    lane_ids: list[str] = Field(default_factory=list)
    lanes: list[str] = Field(default_factory=list)
    questions_recap: list[ReviewQuestionRecap] = Field(default_factory=list)
    whole_project: bool


class AgentTokenIssued(ApiModel):
    """Токен агента по ссылке проверки: секрет показывается один раз."""

    token_id: UUID
    secret: str = Field(description="Секрет вида `bps_…`; в списке токенов его нет")
    name: str
    project_id: UUID
    lane_ids: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)
    expires_at: datetime
    mcp_url: str = Field(description="Адрес MCP-сервера для подключения")
    command: str = Field(description="Команда `claude mcp add …` с уже подставленным токеном")


class AgentActivityEvent(ApiModel):
    """Событие журнала активности агента в проекте (v1 — из существующих данных)."""

    kind: str = Field(description="`source_added` — агент добавил материал, `answer_added` — ответ")
    at: datetime
    token_name: str | None = Field(default=None, description="Название токена доступа")
    title: str | None = None
    detail: str | None = None
    share_link_id: UUID | None = Field(
        default=None, description="Ответ дан по ссылке проверки, если задано"
    )
    source_id: UUID | None = None
    question_id: UUID | None = None
    question_code: str | None = None


class AgentActivity(ApiModel):
    items: list[AgentActivityEvent]
    total: int


class ShareAccepted(ApiModel):
    project_id: UUID
    role: ShareRole


class ProjectMemberRead(ApiModel):
    user_id: UUID
    email: str
    role: ShareRole
    added_at: datetime
