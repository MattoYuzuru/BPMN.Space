"""Связка агентного цикла RFC-0004 с прогоном: вход агента, проверки и восстановление.

`llm/agent.py` не знает ни о БД, ни о версиях схемы: он получает оглавление источников,
обратные вызовы поиска и проверки IR. Этот модуль собирает вход из `RunContext` и `Source`,
проверяет представленный IR тем же кодом, что конвейер (`accept_submitted_ir`), и хранит
сданный результат в `ir.execution.agent` — без текстов источников, только план, журнал хешей
инструментов и канонический IR (цитаты оснований уже лежат в `run.ir`).

Восстановление после рестарта (ADR-0008) не платит за прогон повторно: если `submit` был
принят, сохранённые вопросы и граф проверяются заново по текущим источникам и вопросам. Если
проверка не проходит, прогон завершается понятной ошибкой, а не молча идёт с устаревшим
результатом. Незавершённый цикл перезапускается с тем же счётчиком израсходованных ходов.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.domain.analysis import AnalysisResult, ContextSource, DiagramDraft, NewQuestion, RunContext
from app.domain.models import (
    LintIssue,
    QuestionKind,
    Quote,
    Run,
    Severity,
    Source,
    SourceStatus,
    SourceTrust,
)
from app.llm.agent import (
    AGENT_PROMPT_VERSION,
    AgentInput,
    AgentLimits,
    AgentQuestionView,
    AgentRejectedError,
    AgentSource,
)
from app.llm.base import PipelineError
from app.llm.capabilities import RunProfile
from app.llm.graph_generation import GraphRejectedError, accept_submitted_ir

type VerifyQuote = Callable[[list[ContextSource], object, object], tuple[UUID | None, str | None]]
type GraphLint = Callable[[str], Awaitable[list[LintIssue]]]

# Сколько последних вызовов инструментов хранить в ir.execution.agent: аудит, не архив.
MAX_RECORDED_TOOLS = 100
RECORD_VERSION = AGENT_PROMPT_VERSION


@dataclass(frozen=True, slots=True)
class AgentSubmission:
    """Принятый `submit`: вопросы, черновик схемы и журнал ходов агента."""

    analysis: AnalysisResult
    draft: DiagramDraft | None
    steps: int
    journal: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    warnings: list[str] = field(default_factory=list[str])

    @property
    def prompt_version(self) -> str:
        return RECORD_VERSION

    def record(self) -> dict[str, Any]:
        """Снимок для `ir.execution.agent`: канонический IR и вопросы без текстов источников."""
        return {
            "version": self.prompt_version,
            "submitted": True,
            "steps": self.steps,
            "tools": self.journal[-MAX_RECORDED_TOOLS:],
            "questions": [_question_record(question) for question in self.analysis.new_questions],
            "graph": self.draft.ir if self.draft is not None else None,
            "warnings": self.warnings,
        }


def started_record(steps: int, journal: list[dict[str, Any]]) -> dict[str, Any]:
    """Незавершённый цикл: сколько ходов оплачено и что вызывалось (без результата submit)."""
    return {
        "version": RECORD_VERSION,
        "submitted": False,
        "steps": max(steps, 0),
        "tools": journal[-MAX_RECORDED_TOOLS:],
    }


def recorded_state(run: Run) -> dict[str, Any] | None:
    """Сохранённое состояние агентного прогона из `ir.execution.agent`."""
    execution = (run.ir or {}).get("execution")
    if not isinstance(execution, dict):
        return None
    value = execution.get("agent")
    return value if isinstance(value, dict) else None


def recorded_steps(state: dict[str, Any] | None) -> int:
    """Оплаченные ходы из записи: бюджет ходов продолжается, а не начинается заново."""
    if not isinstance(state, dict):
        return 0
    steps = state.get("steps")
    return steps if isinstance(steps, int) and not isinstance(steps, bool) and steps > 0 else 0


def build_agent_input(
    run: Run,
    context: RunContext,
    sources: list[Source],
    *,
    limits: AgentLimits,
    steps_spent: int,
    profile: RunProfile | None,
) -> AgentInput:
    """Оглавление материалов и существующие вопросы для стартового сообщения агента.

    `read_source` получает полный доступный текст из снимка контекста; источники без текста
    видны в `list_sources` с причиной, но не читаются. Вопросы — только бизнес-вопросы:
    технические (RFC-0006) к процессу не относятся и в IR не попадают.
    """
    evidence = {
        source.id: source.content for source in (context.evidence_sources or context.sources)
    }
    agent_sources: list[AgentSource] = []
    for source in sources:
        content = evidence.get(source.id, "")
        agent_sources.append(
            AgentSource(
                id=source.id,
                title=source.title,
                kind=source.kind,
                content=content,
                created_at=source.created_at,
                warning=source.warning,
                unreadable_pages=tuple(source.unreadable_pages),
                unavailable_reason=_unavailable_reason(source, has_content=bool(content.strip())),
            )
        )
    views = [
        AgentQuestionView(
            code=question.code,
            status=question.status.value,
            kind=question.kind.value,
            text=question.text,
            assumption=question.assumption,
        )
        for question in context.questions
    ]
    budget = profile.budget if profile is not None else None
    return AgentInput(
        project_title=context.project_title,
        project_description=None,
        mode=run.mode,
        sources=tuple(agent_sources),
        questions=tuple(views),
        current_xml_chars=len(context.current_xml or ""),
        generated_versions=context.generated_versions,
        manual_edits=len(context.manual_overrides or {}),
        limits=limits,
        steps_spent=steps_spent,
        budget_tokens=budget.tokens if budget is not None else None,
        budget_cost_usd=budget.cost_usd if budget is not None else None,
    )


def _unavailable_reason(source: Source, *, has_content: bool) -> str | None:
    if has_content:
        return None
    if source.trust is SourceTrust.SUMMARY:
        return "краткое содержание не служит основанием и не читается моделью"
    if not source.active:
        return "источник выключен"
    if source.status is not SourceStatus.READY:
        return "источник ещё не разобран"
    return "у источника нет текста"


async def check_submitted_graph(
    data: object,
    context: RunContext,
    verify_quote: VerifyQuote,
    *,
    lint: GraphLint | None = None,
) -> DiagramDraft:
    """Проверяет IR агента (`check_graph` и `submit`): те же правила, что у конвейера.

    `GraphRejectedError` переводится в `AgentRejectedError`: агентный цикл возвращает ошибки
    модели, не меняя проект.
    """
    try:
        return await accept_submitted_ir(data, context, verify_quote, lint=lint)
    except GraphRejectedError as error:
        raise AgentRejectedError(error.errors) from None


async def restore_submission(
    state: dict[str, Any] | None,
    context: RunContext,
    verify_quote: VerifyQuote,
    *,
    lint: GraphLint | None = None,
) -> AgentSubmission | None:
    """Принятый ранее submit после рестарта: повторная проверка без повторной оплаты.

    Возвращает `None`, если записи нет, submit не состоялся или версия промпта другая — тогда
    цикл выполняется заново (с уже потраченными ходами в счётчике). Если сохранённый граф или
    цитаты больше не проходят проверку по текущим материалам, вызывает `PipelineError`:
    устаревший результат не публикуется как успешный.
    """
    if not isinstance(state, dict) or not state.get("submitted"):
        return None
    if state.get("version") != RECORD_VERSION:
        return None
    graph = state.get("graph")
    draft: DiagramDraft | None = None
    if graph is not None:
        try:
            draft = await check_submitted_graph(graph, context, verify_quote, lint=lint)
        except AgentRejectedError as error:
            raise PipelineError(
                "Сданный агентный результат не прошёл повторную проверку после рестарта: "
                + "; ".join(error.errors[:5])
            ) from None
    questions: list[NewQuestion] = []
    sources = context.evidence_sources or context.sources
    for item in state.get("questions") or []:
        try:
            questions.append(_question_from_record(item, sources, verify_quote))
        except (KeyError, TypeError, ValueError) as error:
            raise PipelineError(
                f"Сданные агентные вопросы не прошли повторную проверку после рестарта: {error}"
            ) from None
    warnings = [str(item) for item in state.get("warnings") or []]
    return AgentSubmission(
        analysis=AnalysisResult(new_questions=questions),
        draft=draft,
        steps=recorded_steps(state),
        journal=[dict(item) for item in state.get("tools") or [] if isinstance(item, dict)],
        warnings=warnings,
    )


def _question_record(question: NewQuestion) -> dict[str, Any]:
    about = question.about
    return {
        "kind": question.kind.value,
        "severity": question.severity.value,
        "text": question.text,
        "assumption": question.assumption,
        "about": {"source_id": str(about.source_id), "quote": about.quote} if about else None,
        "element_ids": list(question.element_ids),
    }


def _question_from_record(
    item: object,
    sources: list[ContextSource],
    verify_quote: VerifyQuote,
) -> NewQuestion:
    if not isinstance(item, dict):
        raise ValueError("вопрос: ожидался объект")
    about: Quote | None = None
    raw = item.get("about")
    if isinstance(raw, dict):
        source_id, quote = verify_quote(sources, raw.get("source_id"), raw.get("quote"))
        if source_id is None or quote is None:
            raise ValueError("цитата вопроса больше не найдена в источниках")
        about = Quote(source_id=source_id, quote=quote)
    return NewQuestion(
        kind=QuestionKind(item["kind"]),
        severity=Severity(item["severity"]),
        text=str(item["text"]),
        assumption=str(item.get("assumption") or ""),
        about=about,
        element_ids=[str(value) for value in item.get("element_ids") or []],
    )


def effective_limits(
    profile: RunProfile | None,
    *,
    server_steps: int,
    read_max_chars: int,
    search_limit: int,
    snippet_chars: int,
) -> AgentLimits:
    """Лимиты прогона: профиль может попросить меньше ходов, но не больше серверного потолка."""
    requested = profile.max_steps if profile is not None and profile.max_steps else server_steps
    return AgentLimits(
        max_steps=min(requested, server_steps),
        read_max_chars=read_max_chars,
        search_limit=search_limit,
        search_snippet_chars=snippet_chars,
    ).checked()
