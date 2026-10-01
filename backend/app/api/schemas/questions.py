"""Схемы вопросов."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.api.schemas.common import ApiModel, Quote
from app.domain.models import QuestionKind, QuestionStatus, Severity


class Answer(ApiModel):
    source_id: UUID = Field(description="Источник `kind=answer` с текстом ответа")
    text: str


class Question(ApiModel):
    id: UUID
    project_id: UUID
    code: str = Field(description="Номер внутри проекта: Q-1, Q-2, …")
    kind: QuestionKind
    severity: Severity
    status: QuestionStatus
    text: str
    assumption: str = Field(description="Что модель сделает, если вопрос проигнорировать")
    about: Quote | None = Field(default=None, description="Фрагмент источника, вызвавший вопрос")
    evidence: Quote | None = Field(default=None, description="Доказательство для `resolved`")
    element_ids: list[str] = Field(description="Элементы схемы, которых касается вопрос")
    answer: Answer | None = None
    created_at: datetime
    updated_at: datetime


class QuestionAnswerCreate(ApiModel):
    text: str = Field(min_length=1, description="Ответ текстом или проверенная расшифровка голоса")
