"""Сущности предметной области (RFC §5.7). Чистые dataclass-ы, без I/O и фреймворков.

Репозитории (`app/infra/repositories`) хранят и отдают именно их; API-схемы (`app/api/schemas`)
строятся из них через `from_attributes`. Поля, которых нет в API (например, `file_key`),
помечены комментарием «внутреннее».
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class ProjectStatus(StrEnum):
    EMPTY = "empty"
    ANALYZING = "analyzing"
    NEEDS_ANSWERS = "needs_answers"
    READY = "ready"
    BUILDING = "building"


class SourceKind(StrEnum):
    TEXT = "text"
    VOICE = "voice"
    FILE = "file"
    ANSWER = "answer"


class SourceStatus(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class QuestionKind(StrEnum):
    MISSING_ACTOR = "missing_actor"
    AMBIGUOUS_CONDITION = "ambiguous_condition"
    UNCLEAR_ORDER = "unclear_order"
    MISSING_OUTCOME = "missing_outcome"
    CONFLICT = "conflict"


class Severity(StrEnum):
    BLOCKER = "blocker"
    MAJOR = "major"
    MINOR = "minor"


class QuestionStatus(StrEnum):
    OPEN = "open"
    ANSWERED = "answered"
    IGNORED = "ignored"
    RESOLVED = "resolved"
    OBSOLETE = "obsolete"


class RunMode(StrEnum):
    ANALYZE = "analyze"
    BUILD = "build"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RunStage(StrEnum):
    READING_SOURCES = "reading_sources"
    EXTRACTING = "extracting"
    RECONCILING = "reconciling"
    STRUCTURING = "structuring"
    VALIDATING = "validating"
    LAYOUT = "layout"


class VersionOrigin(StrEnum):
    GENERATED = "generated"
    MANUAL = "manual"


class LintSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(slots=True, kw_only=True)
class Quote:
    """Ссылка на фрагмент источника: id источника и точная цитата из его текста."""

    source_id: UUID
    quote: str


@dataclass(slots=True, kw_only=True)
class Answer:
    source_id: UUID
    text: str


@dataclass(slots=True, kw_only=True)
class Project:
    id: UUID
    title: str
    description: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True, kw_only=True)
class Source:
    id: UUID
    project_id: UUID
    kind: SourceKind
    title: str
    content: str
    status: SourceStatus
    active: bool
    created_at: datetime
    file_name: str | None = None
    mime: str | None = None
    size_bytes: int | None = None
    duration_sec: float | None = None
    question_id: UUID | None = None
    error: str | None = None
    file_key: str | None = None  # внутреннее: ключ файла в хранилище (infra/storage)
    digest: str | None = None  # внутреннее: кэш дайджеста источника для контекстного окна


@dataclass(slots=True, kw_only=True)
class Question:
    id: UUID
    project_id: UUID
    code: str
    kind: QuestionKind
    severity: Severity
    status: QuestionStatus
    text: str
    assumption: str
    created_at: datetime
    updated_at: datetime
    about: Quote | None = None
    evidence: Quote | None = None
    element_ids: list[str] = field(default_factory=list[str])
    answer: Answer | None = None
    run_id: UUID | None = None  # внутреннее: прогон, который создал вопрос (для счётчика «новых»)


@dataclass(slots=True, kw_only=True)
class RunSummary:
    """Итог прогона по вопросам: «решено N · осталось M · новых K»."""

    resolved: int = 0
    open: int = 0
    new: int = 0
    ignored: int = 0
    answered: int = 0


@dataclass(slots=True, kw_only=True)
class Run:
    id: UUID
    project_id: UUID
    mode: RunMode
    status: RunStatus
    started_at: datetime
    stage: RunStage | None = None
    progress: float = 0.0
    finished_at: datetime | None = None
    summary: RunSummary | None = None
    version_id: UUID | None = None
    error: str | None = None
    # Предупреждения прогона для пользователя: например, часть материалов не вошла в контекст.
    warnings: list[str] = field(default_factory=list[str])
    analysis: dict[str, Any] | None = None  # внутреннее: снимок анализа для аудита и повтора
    ir: dict[str, Any] | None = None  # внутреннее: нормализованная структура прогона
    report: dict[str, Any] | None = None  # внутреннее: итог проверки BPMN
    model: str | None = None  # внутреннее: фактически использованная модель
    latency_ms: int | None = None  # внутреннее: длительность выполнения прогона


@dataclass(slots=True, kw_only=True)
class LlmCall:
    """Запись аудита одного этапа вызова модели (RFC §5.7)."""

    id: UUID
    run_id: UUID
    stage: str
    request: dict[str, Any]
    response: dict[str, Any]
    tokens_in: int | None = None
    tokens_out: int | None = None
    latency_ms: int | None = None


@dataclass(slots=True, kw_only=True)
class VersionDiff:
    added: int = 0
    removed: int = 0
    changed: int = 0


@dataclass(slots=True, kw_only=True)
class LintIssue:
    rule: str
    message: str
    severity: LintSeverity
    element_id: str | None = None


@dataclass(slots=True, kw_only=True)
class AssumptionMark:
    """Элемент схемы, построенный на допущении неотвеченного вопроса."""

    element_id: str
    question_id: UUID
    text: str


@dataclass(slots=True, kw_only=True)
class Report:
    xsd_valid: bool
    lint: list[LintIssue] = field(default_factory=list[LintIssue])
    assumptions: list[AssumptionMark] = field(default_factory=list[AssumptionMark])


@dataclass(slots=True, kw_only=True)
class Version:
    id: UUID
    project_id: UUID
    number: int
    origin: VersionOrigin
    created_at: datetime
    xml: str
    diff: VersionDiff
    report: Report
    trace: dict[str, Quote] = field(default_factory=dict[str, Quote])
    lanes: list[str] = field(default_factory=list[str])
    run_id: UUID | None = None
