"""Сущности предметной области (RFC §5.7). Чистые dataclass-ы, без I/O и фреймворков.

Репозитории (`app/infra/repositories`) хранят и отдают именно их; API-схемы (`app/api/schemas`)
строятся из них через `from_attributes`. Поля, которых нет в API (например, `file_key`),
помечены комментарием «внутреннее».
"""

from dataclasses import dataclass, field
from datetime import date, datetime
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


class SourceOrigin(StrEnum):
    """Откуда источник (RFC-0006): загрузил человек, получен из другого, принёс агент, ответ."""

    USER = "user"
    DERIVED = "derived"
    AGENT = "agent"
    ANSWER = "answer"


class SourceTrust(StrEnum):
    """Уровень доверия (RFC-0006): что из источника можно цитировать в основаниях IR.

    `summary` — только навигация: в контекст модели и в основания не идёт.
    """

    PRIMARY = "primary"
    EXTRACTED = "extracted"
    OBSERVED = "observed"
    EXTERNAL = "external"
    AGENT = "agent"
    SUMMARY = "summary"


class SourceStatus(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class QuestionKind(StrEnum):
    """Бизнес-вопрос: касается процесса и влияет на граф (RFC §2.2)."""

    MISSING_ACTOR = "missing_actor"
    AMBIGUOUS_CONDITION = "ambiguous_condition"
    UNCLEAR_ORDER = "unclear_order"
    MISSING_OUTCOME = "missing_outcome"
    CONFLICT = "conflict"


class QuestionCategory(StrEnum):
    """Категория вопроса (RFC-0006, шаг 2): бизнес-вопрос или технический.

    Технические вопросы касаются материалов и запуска, на граф не влияют и в IR не попадают.
    """

    BUSINESS = "business"
    TECHNICAL = "technical"


class TechnicalQuestionKind(StrEnum):
    """Тип технического вопроса: что именно мешает прогону или чтению материалов."""

    QUOTA_EXHAUSTED = "quota_exhausted"
    CREDENTIAL_INVALID = "credential_invalid"
    CAPABILITY_MISSING = "capability_missing"
    BUDGET_REACHED = "budget_reached"
    INPUT_INCOMPLETE = "input_incomplete"


class QuestionActionKind(StrEnum):
    """Действие по техническому вопросу вместо текстового ответа (RFC-0006)."""

    OPEN_SETTINGS = "open_settings"
    RETRY = "retry"
    CONTINUE_WITHOUT = "continue_without"
    RAISE_BUDGET = "raise_budget"


QUESTION_ACTION_LABELS: dict[QuestionActionKind, str] = {
    QuestionActionKind.OPEN_SETTINGS: "Открыть настройки",
    QuestionActionKind.RETRY: "Повторить",
    QuestionActionKind.CONTINUE_WITHOUT: "Продолжить без этого",
    QuestionActionKind.RAISE_BUDGET: "Поднять бюджет",
}


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
    # Ждёт действия пользователя по блокирующему техническому вопросу (RFC-0006).
    WAITING = "waiting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


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


#: Провенанс ответа: его записал внешний агент владельца токена (RFC-0007), а не человек.
ANSWER_VIA_AGENT = "agent"


@dataclass(slots=True, kw_only=True)
class Answer:
    source_id: UUID
    text: str
    # `via=agent` — ответ пришёл через MCP внешнего агента; `via_name` — название токена.
    # Сервер не может проверить, читал ли человек ответ перед отправкой, и не делает вид, что может.
    via: str | None = None
    via_name: str | None = None
    # Ответ дан по ссылке проверки (RFC-0007, шаг 3): id ссылки, если токен агента выдан ею.
    share_link_id: UUID | None = None


@dataclass(slots=True, kw_only=True)
class Project:
    id: UUID
    title: str
    description: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True, kw_only=True)
class SourceDerivation:
    """Как получен производный источник: возможность, провайдер, модель, параметры, стоимость."""

    capability: str
    provider: str
    created_at: datetime
    model: str | None = None
    params: dict[str, Any] = field(default_factory=dict[str, Any])
    cost_usd: float | None = None  # None — стоимость неизвестна
    # Ключ пользователя, которым оплачен вызов (`None` — серверный провайдер). Нужен, чтобы
    # учитывать минуты/запросы по плательщику, когда появится расход по ключам.
    credential_id: UUID | None = None


@dataclass(slots=True, kw_only=True)
class MediaInfo:
    """Что `ffprobe` узнал о записи; без ffmpeg (mock) дорожки неизвестны."""

    has_audio: bool | None = None
    has_video: bool | None = None


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
    # Источник готов, но прочитан не полностью (страницы без текстового слоя, обрезанные листы).
    warning: str | None = None
    unreadable_pages: list[int] = field(default_factory=list[int])
    file_key: str | None = None  # внутреннее: ключ файла в хранилище (infra/storage)
    digest: str | None = None  # внутреннее: кэш дайджеста источника для контекстного окна
    # Дерево материалов (RFC-0006): происхождение, родитель того же проекта и доверие.
    origin: SourceOrigin = SourceOrigin.USER
    parent_id: UUID | None = None
    derivation: SourceDerivation | None = None
    trust: SourceTrust = SourceTrust.PRIMARY
    edited_by_human: bool = False  # текст производного источника правил человек
    media: MediaInfo | None = None  # для записи: дорожки звука и видео

    def __post_init__(self) -> None:
        # Ответ на вопрос всегда `origin=answer`: так же заполняет и миграция 0016.
        if self.kind is SourceKind.ANSWER and self.origin is SourceOrigin.USER:
            self.origin = SourceOrigin.ANSWER

    @property
    def feeds_model(self) -> bool:
        """Идёт ли текст в контекст прогона: активный, готовый, с текстом и не краткое содержание.

        Родитель-запись без текста не идёт: её текст лежит в производной расшифровке, и
        цитаты оснований ссылаются на неё.
        """
        return (
            self.active
            and self.status is SourceStatus.READY
            and bool(self.content.strip())
            and self.trust is not SourceTrust.SUMMARY
        )


@dataclass(slots=True, kw_only=True)
class QuestionAction:
    """Действие по техническому вопросу; подпись показывает интерфейс, payload — параметры."""

    kind: QuestionActionKind
    label: str
    payload: dict[str, Any] = field(default_factory=dict[str, Any])


@dataclass(slots=True, kw_only=True)
class Question:
    id: UUID
    project_id: UUID
    code: str
    kind: QuestionKind | TechnicalQuestionKind
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
    # RFC-0006, шаг 2: бизнес-вопрос (по умолчанию) или технический; у технического — действия
    # вместо текстового ответа; блокирующий технический вопрос переводит прогон в `waiting`.
    category: QuestionCategory = QuestionCategory.BUSINESS
    actions: list[QuestionAction] = field(default_factory=list[QuestionAction])
    blocking: bool = False

    @property
    def is_technical(self) -> bool:
        return self.category is QuestionCategory.TECHNICAL


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
    created_by: UUID | None = None  # внутреннее: кто запустил прогон (учёт прогресса онбординга)
    # Предупреждения прогона для пользователя: например, часть материалов не вошла в контекст.
    warnings: list[str] = field(default_factory=list[str])
    analysis: dict[str, Any] | None = None  # внутреннее: снимок анализа для аудита и повтора
    ir: dict[str, Any] | None = None  # внутреннее: нормализованная структура прогона
    report: dict[str, Any] | None = None  # внутреннее: итог проверки BPMN
    model: str | None = None  # внутреннее: фактически использованная модель
    latency_ms: int | None = None  # внутреннее: длительность выполнения прогона
    actor_email: str | None = None  # кто запустил прогон; снимок для истории


@dataclass(slots=True, kw_only=True)
class LlmCall:
    """Запись аудита одного этапа вызова модели (RFC §5.7).

    `tokens_in` — все входные токены этапа, включая кеш; `cache_read_tokens` и
    `cache_write_tokens` — его части. `cost_usd` — цена по справочнику на момент вызова
    (`price_checked_on`), `None` — цены модели неизвестны (совместимый провайдер, mock).
    """

    id: UUID
    run_id: UUID
    stage: str
    request: dict[str, Any]
    response: dict[str, Any]
    tokens_in: int | None = None
    tokens_out: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    cost_usd: float | None = None
    price_checked_on: date | None = None
    model: str | None = None
    latency_ms: int | None = None


@dataclass(slots=True, kw_only=True)
class LlmCallTotals:
    """Итог вызовов модели по прогону и по этапам (для стоимости в интерфейсе).

    `priced_calls` — сколько вызовов имеет цену; `usage_calls` — сколько сообщило токены;
    `neutral_calls` — вызовы, прерванные до запроса к провайдеру (ошибка без токенов).
    `complete` означает, что у каждого состоявшегося вызова известны и токены, и цена: шаг,
    который не дошёл до модели, не делает итог неполным навсегда. `stages` — разбивка по
    названию этапа пайплайна (analyze, structure, …).
    """

    calls: int = 0
    usage_calls: int = 0
    priced_calls: int = 0
    neutral_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    stages: dict[str, "LlmCallTotals"] = field(default_factory=dict[str, "LlmCallTotals"])

    @property
    def complete(self) -> bool:
        if self.calls <= 0:
            return False
        measured = self.calls - self.neutral_calls
        return self.usage_calls == measured and self.priced_calls == measured

    @classmethod
    def of_stages(cls, stages: dict[str, "LlmCallTotals"]) -> "LlmCallTotals":
        """Складывает итоги этапов в итог прогона, сохраняя разбивку."""
        total = cls(stages=dict(stages))
        for item in stages.values():
            total.calls += item.calls
            total.usage_calls += item.usage_calls
            total.priced_calls += item.priced_calls
            total.neutral_calls += item.neutral_calls
            total.tokens_in += item.tokens_in
            total.tokens_out += item.tokens_out
            total.cache_read_tokens += item.cache_read_tokens
            total.cache_write_tokens += item.cache_write_tokens
            total.cost_usd += item.cost_usd
        return total


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
class VersionSummary:
    """Строка истории: без XML, цитат и полного отчёта, только счётчики проверки."""

    id: UUID
    project_id: UUID
    number: int
    origin: VersionOrigin
    created_at: datetime
    diff: VersionDiff
    lint_count: int
    assumption_count: int
    run_id: UUID | None
    actor_email: str | None
    label: str | None
    checkpoint: bool
    session_started_at: datetime
    updated_at: datetime
    saved_count: int


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
    actor_email: str | None = None  # кто создал версию; для старых записей неизвестен
    label: str | None = None  # имя контрольной точки
    checkpoint: bool = False  # закреплена человеком: сессия правок на ней закрыта
    session_started_at: datetime | None = None  # начало сессии правок; по умолчанию created_at
    updated_at: datetime | None = None  # последнее автосохранение, влитое в версию
    saved_count: int = 1  # сколько сохранений влито в версию

    def __post_init__(self) -> None:
        self.session_started_at = self.session_started_at or self.created_at
        self.updated_at = self.updated_at or self.created_at

    @property
    def lint_count(self) -> int:
        return len(self.report.lint)

    @property
    def assumption_count(self) -> int:
        return len(self.report.assumptions)

    def summary(self) -> VersionSummary:
        return VersionSummary(
            id=self.id,
            project_id=self.project_id,
            number=self.number,
            origin=self.origin,
            created_at=self.created_at,
            diff=self.diff,
            lint_count=self.lint_count,
            assumption_count=self.assumption_count,
            run_id=self.run_id,
            actor_email=self.actor_email,
            label=self.label,
            checkpoint=self.checkpoint,
            session_started_at=self.session_started_at or self.created_at,
            updated_at=self.updated_at or self.created_at,
            saved_count=self.saved_count,
        )
