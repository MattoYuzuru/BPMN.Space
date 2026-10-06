"""Вход и выход LLM-пайплайна (RFC §5.1–5.3) в виде, не зависящем от провайдера.

`RunContext` собирает `ingest/context.py`, `AnalysisResult` и `DiagramDraft` возвращает реализация
`app.llm.base.ProcessPipeline` (сейчас — `app.llm.mock.MockPipeline`).
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from app.domain.models import (
    Question,
    QuestionKind,
    QuestionStatus,
    Quote,
    Severity,
    SourceKind,
)

MAX_SOURCE_TEXT_CHARS = 40_000


@dataclass(slots=True, kw_only=True)
class ContextSource:
    id: UUID
    kind: SourceKind
    title: str
    content: str
    created_at: datetime


@dataclass(slots=True, kw_only=True)
class RunContext:
    """Всё, что видит модель за один прогон: источники с id, вопросы, текущая схема."""

    project_id: UUID
    project_title: str
    sources: list[ContextSource]
    questions: list[Question]
    current_xml: str | None = None
    current_is_manual: bool = False
    generated_versions: int = 0
    current_trace: dict[str, Quote] = field(default_factory=dict[str, Quote])
    evidence_sources: list[ContextSource] = field(default_factory=list[ContextSource])
    base_version_id: UUID | None = None
    base_generated_xml: str | None = None
    replace_manual: bool = False
    manual_overrides: dict[str, Any] | None = None
    # Что не поместилось в бюджет контекста и было обрезано или пропущено (показываем в прогоне).
    warnings: list[str] = field(default_factory=list[str])


@dataclass(slots=True, kw_only=True)
class QuestionUpdate:
    """Изменение статуса существующего вопроса по итогам анализа (ссылка — по коду `Q-N`)."""

    code: str
    status: QuestionStatus
    evidence: Quote | None = None
    reason: str | None = None


@dataclass(slots=True, kw_only=True)
class NewQuestion:
    kind: QuestionKind
    severity: Severity
    text: str
    assumption: str
    about: Quote | None = None
    element_ids: list[str] = field(default_factory=list[str])


@dataclass(slots=True, kw_only=True)
class AnalysisResult:
    question_updates: list[QuestionUpdate] = field(default_factory=list[QuestionUpdate])
    new_questions: list[NewQuestion] = field(default_factory=list[NewQuestion])


@dataclass(slots=True, kw_only=True)
class DiagramDraft:
    """Готовая к проверке схема: BPMN XML и трассировка «элемент → цитата»."""

    xml: str
    trace: dict[str, Quote] = field(default_factory=dict[str, Quote])
    ir: dict[str, Any] | None = None
    bindings: dict[str, list[str]] = field(default_factory=dict[str, list[str]])
    warnings: list[str] = field(default_factory=list[str])
    conflicts: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    manual_overrides: dict[str, Any] | None = None
