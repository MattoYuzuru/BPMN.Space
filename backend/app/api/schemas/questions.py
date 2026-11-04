"""Схемы вопросов: бизнес-вопросы процесса и технические вопросы запуска (RFC-0006)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from app.api.schemas.budget import RunBudget
from app.api.schemas.common import ApiModel, Quote
from app.domain.models import (
    QuestionActionKind,
    QuestionCategory,
    QuestionKind,
    QuestionStatus,
    Severity,
    TechnicalQuestionKind,
)


class Answer(ApiModel):
    source_id: UUID = Field(description="Источник `kind=answer` с текстом ответа")
    text: str
    via: str | None = Field(
        default=None,
        description="`agent` — ответ записал внешний агент владельца токена (MCP, RFC-0007); "
        "`review` — проверяющий ответил по ссылке проверки; null — человек в интерфейсе",
    )
    via_name: str | None = Field(
        default=None, description="Название токена доступа, которым ответил агент"
    )
    share_link_id: UUID | None = Field(
        default=None,
        description="Ответ дан по ссылке проверки (RFC-0007, шаг 3): id ссылки",
    )


class QuestionAction(ApiModel):
    """Действие по техническому вопросу вместо текстового ответа."""

    kind: QuestionActionKind = Field(
        description="open_settings — открыть настройки; retry — повторить; "
        "continue_without — продолжить без этого; raise_budget — поднять бюджет"
    )
    label: str = Field(description="Подпись для интерфейса")
    payload: dict[str, Any] = Field(default_factory=dict)


class Question(ApiModel):
    id: UUID
    project_id: UUID
    code: str = Field(description="Номер внутри проекта: Q-1, Q-2, …")
    kind: QuestionKind | TechnicalQuestionKind = Field(
        description="Тип: бизнес-вопрос процесса или технический вопрос запуска"
    )
    category: QuestionCategory = Field(
        default=QuestionCategory.BUSINESS,
        description="`business` влияет на граф, `technical` касается материалов и запуска",
    )
    severity: Severity
    status: QuestionStatus
    text: str
    assumption: str = Field(description="Что модель сделает, если вопрос проигнорировать")
    about: Quote | None = Field(default=None, description="Фрагмент источника, вызвавший вопрос")
    evidence: Quote | None = Field(default=None, description="Доказательство для `resolved`")
    element_ids: list[str] = Field(description="Элементы схемы, которых касается вопрос")
    answer: Answer | None = None
    actions: list[QuestionAction] = Field(
        default_factory=list,
        description="Действия технического вопроса; у бизнес-вопроса пусто",
    )
    blocking: bool = Field(
        default=False,
        description="Блокирующий технический вопрос переводит прогон в `waiting`",
    )
    created_at: datetime
    updated_at: datetime


class QuestionAnswerCreate(ApiModel):
    text: str = Field(min_length=1, description="Ответ текстом или проверенная расшифровка голоса")


class QuestionActionRequest(ApiModel):
    """Действие по техническому вопросу; для `raise_budget` нужен новый бюджет."""

    action: QuestionActionKind
    budget: RunBudget | None = Field(
        default=None, description="Новый бюджет для действия `raise_budget` (только рост)"
    )
