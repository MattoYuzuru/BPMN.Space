"""Прогоны (RFC §5.1): запуск `202`, выполнение этапов в фоне, события для SSE.

Не больше `max_concurrent_runs` прогонов одновременно (остальные ждут в `queued`), по одному
активному прогону на проект (повторный запуск → 409). Каждый этап публикует `stage`;
сверка вопросов — `question` на каждый изменённый или новый вопрос и `summary`; сборка — `version`;
последним всегда идёт `done` (при ошибке ему предшествует `error`).
"""

import asyncio
import json
import logging
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from copy import deepcopy
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from datetime import date, datetime
from enum import Enum
from typing import Any, Protocol
from uuid import UUID

from app.domain.analysis import AnalysisResult, ContextSource, DiagramDraft, NewQuestion, RunContext
from app.domain.bpmn.document import BpmnFormatError
from app.domain.bpmn.importer import preserve_geometry
from app.domain.bpmn.xsd import xsd_errors
from app.domain.models import (
    LlmCall,
    Question,
    QuestionKind,
    QuestionStatus,
    Quote,
    Run,
    RunMode,
    RunStage,
    RunStatus,
    Severity,
    Source,
    SourceKind,
    SourceStatus,
    Version,
    VersionOrigin,
)
from app.domain.onboarding import ChecklistItem
from app.domain.questions import quote_in_source, reconcile, run_summary
from app.domain.runs import (
    ACTIVE_STATUSES,
    RunError,
    RunEvent,
    RunEventKind,
    StageProgress,
    progress_at,
    stage_label,
    stages_for,
)
from app.infra.bpmn_tools import BpmnTools, BpmnToolsError
from app.infra.events import RunEventBus
from app.infra.repositories.base import ActiveRunConflictError, Repositories
from app.infra.tasks import TaskSpawner
from app.ingest.context import build_run_context, describe_context, source_snapshot_hash
from app.llm.base import (
    DEADLINE_MESSAGE,
    PipelineError,
    ProcessPipeline,
    run_deadline,
    track_usage,
)
from app.services.common import Runtime, get_project, get_run
from app.services.errors import ConflictError, NotFoundError, StaleVersionError
from app.services.versions import add_version

logger = logging.getLogger(__name__)

type Pace = Callable[[RunStage], Awaitable[None]]
type RealtimePublisher = Callable[[UUID, dict[str, object]], Awaitable[None]]


class ProgressRecorder(Protocol):
    """Порт учёта первых действий пользователя (чек-лист онбординга).

    Реализация — `OnboardingService`, подключается в `container.py`: прогон завершается в фоне,
    где текущего пользователя уже нет, поэтому отмечает того, кто его запустил (`created_by`).
    Реализация не должна бросать исключения: учёт не ломает прогон.
    """

    async def record(self, user_id: UUID | None, item: ChecklistItem) -> bool: ...


async def no_pace(stage: RunStage) -> None:  # noqa: ARG001 — сигнатура Pace
    return None


def _json_data(value: Any) -> Any:
    """Приводит объекты domain к JSON-совместимым снимкам без зависимости от API-слоя."""
    if is_dataclass(value) and not isinstance(value, type):
        return _json_data(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_data(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_data(item) for item in value]
    if isinstance(value, (UUID, datetime, date)):
        return str(value) if isinstance(value, UUID) else value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value


_INTERNAL_ERROR = "Внутренняя ошибка прогона, попробуйте ещё раз"


@dataclass(slots=True)
class _RunState:
    context: RunContext | None = None
    analysis: AnalysisResult = field(default_factory=AnalysisResult)
    draft: DiagramDraft | None = None
    xml: str | None = None


def _source_snapshot(
    sources: list[Source] | list[ContextSource],
) -> list[tuple[str, str, str, str, str]]:
    return sorted(
        (str(s.id), s.kind.value, s.title, s.content, s.created_at.isoformat())
        for s in sources
        if not isinstance(s, Source)
        or (s.active and s.status is SourceStatus.READY and s.content.strip())
    )


def _question_snapshot(questions: list[Question]) -> list[str]:
    return sorted(json.dumps(_json_data(q), sort_keys=True, ensure_ascii=False) for q in questions)


def _conflict_value(value: dict[str, Any], graph: dict[str, Any]) -> str:
    lanes = {item["id"]: item["name"] for item in graph.get("lanes", [])}
    nodes = {item["id"]: item["name"] for item in graph.get("nodes", [])}
    if "source_id" in value and "target_id" in value:
        start = nodes.get(value["source_id"], value["source_id"])
        end = nodes.get(value["target_id"], value["target_id"])
        route = f"«{start}» → «{end}»"
        condition = value.get("condition") or (
            "иначе" if value.get("default") else value.get("name")
        )
        return f"{route}, условие «{condition}»" if condition else route
    label = f"«{value.get('name', 'Элемент')}»"
    if value.get("lane"):
        label += f", исполнитель «{lanes.get(value['lane'], value['lane'])}»"
    return label


class RunService:
    def __init__(
        self,
        repos: Repositories,
        *,
        pipeline: ProcessPipeline,
        bpmn_tools: BpmnTools,
        events: RunEventBus,
        spawner: TaskSpawner,
        runtime: Runtime,
        max_concurrent: int,
        pace: Pace = no_pace,
        context_budget_chars: int = 120_000,
        deadline_sec: float = 600.0,
        progress: ProgressRecorder | None = None,
        broadcast: RealtimePublisher | None = None,
    ) -> None:
        self._repos = repos
        self._pipeline = pipeline
        self._tools = bpmn_tools
        self._events = events
        self._spawner = spawner
        self._rt = runtime
        self._pace = pace
        self._context_budget = context_budget_chars
        self._deadline_sec = deadline_sec
        self._progress = progress
        self._broadcast = broadcast
        self._limit = asyncio.Semaphore(max(max_concurrent, 1))
        self._cancel_requested: set[UUID] = set()
        # Этот lock ускоряет конфликт внутри процесса; уникальный индекс защищает между процессами.
        self._start_lock = asyncio.Lock()

    async def start(
        self,
        project_id: UUID,
        *,
        mode: RunMode,
        created_by: UUID | None,
        actor_email: str | None = None,
        base_version_id: UUID | None = None,
        replace_manual: bool = False,
    ) -> Run:
        async with self._start_lock, self._repos.atomic() as repos:
            # Блокировка проекта общая с ручным сохранением схемы и удалением проекта.
            if await repos.projects.lock(project_id) is None:
                raise NotFoundError("Проект не найден")
            if await repos.runs.active_for_project(project_id):
                raise ConflictError("По проекту уже идёт прогон — дождитесь его завершения")
            sources = await repos.sources.list_by_project(project_id)
            usable = [
                s
                for s in sources
                if s.active and s.status is SourceStatus.READY and s.kind is not SourceKind.ANSWER
            ]
            if not usable:
                raise ConflictError("Добавьте хотя бы один источник с текстом")
            head = await repos.versions.latest(project_id)
            if base_version_id is not None and (head.id if head else None) != base_version_id:
                raise StaleVersionError(head.id if head else None, head.number if head else None)
            now = self._rt.clock()
            run = Run(
                id=self._rt.new_id(),
                project_id=project_id,
                mode=mode,
                status=RunStatus.QUEUED,
                started_at=now,
                created_by=created_by,
                model=getattr(self._pipeline, "model_name", type(self._pipeline).__name__),
                actor_email=actor_email,
                ir={
                    "execution": {
                        "base_version_id": str(head.id) if head else None,
                        "replace_manual": replace_manual,
                    }
                },
            )
            try:
                await repos.runs.add(run)
            except ActiveRunConflictError as error:
                raise ConflictError(
                    "По проекту уже идёт прогон — дождитесь его завершения"
                ) from error
            await repos.projects.touch(project_id, now)
        await self._publish_live(run)
        self._spawner.spawn(self._execute(run.id), name=f"run-{run.id}")
        return run

    async def get(self, run_id: UUID) -> Run:
        return await get_run(self._repos, run_id)

    async def cancel(self, run_id: UUID) -> Run:
        """Отменить общий прогон проекта; безопасно повторяется после его завершения."""
        run = await get_run(self._repos, run_id)
        if run.status not in ACTIVE_STATUSES:
            return run

        # Сначала даём активному исполнителю обработать CancelledError и сохранить терминальный
        # статус. Для задачи, ещё ожидающей семафор, coroutine может вообще не начать работу —
        # тогда статус фиксируем здесь.
        self._cancel_requested.add(run_id)
        try:
            cancelled_task = await self._spawner.cancel(name=f"run-{run_id}")
        finally:
            self._cancel_requested.discard(run_id)
        current = await get_run(self._repos, run_id)
        if current.status in ACTIVE_STATUSES:
            current.status = RunStatus.CANCELLED
            current.error = "Прогон отменён участником"
            current.finished_at = self._rt.clock()
            await self._repos.runs.update(current)
            await self._publish(current, RunEventKind.DONE, current)
        elif not cancelled_task:
            return current
        return await get_run(self._repos, run_id)

    async def events(self, run_id: UUID, *, after: int = 0) -> AsyncIterator[RunEvent]:
        """Поток событий; для прогона без журнала (сид, рестарт) — сразу итоговый `done`."""
        run = await get_run(self._repos, run_id)
        if not self._events.has_log(run_id) and run.status not in ACTIVE_STATUSES:
            return self._single_done(run, after=after)
        return self._events.subscribe(run_id, after=after)

    @staticmethod
    async def _single_done(run: Run, *, after: int) -> AsyncIterator[RunEvent]:
        if after < 1:
            yield RunEvent(id=1, kind=RunEventKind.DONE, payload=run)

    async def _execute(self, run_id: UUID) -> None:
        async with self._limit:
            run: Run | None = None
            try:
                run = await self._repos.runs.get(run_id)
                if run is not None:
                    await self._drive(run)
            finally:
                # Что бы ни случилось (в том числе сбой чтения прогона из БД), подписчики SSE
                # получают `done`: иначе поток висел бы вечно. Повтор `done` шина игнорирует.
                # Если прогона нет в БД без ошибки чтения, закрывать нечего.
                if run is not None or sys.exc_info()[0] is not None:
                    lost = run or self._lost_run(run_id)
                    await self._publish(lost, RunEventKind.DONE, lost)

    def _lost_run(self, run_id: UUID) -> Run:
        """Заглушка для финального `done`, когда прогон не удалось прочитать из БД."""
        return Run(
            id=run_id,
            project_id=UUID(int=0),
            mode=RunMode.ANALYZE,
            status=RunStatus.FAILED,
            started_at=self._rt.clock(),
            error=_INTERNAL_ERROR,
        )

    async def _drive(self, run: Run) -> None:
        execution_started = time.perf_counter()
        deadline = self._deadline_sec if self._deadline_sec > 0 else None
        scope: asyncio.Timeout | None = None
        try:
            with run_deadline(deadline):
                async with asyncio.timeout(deadline) as scope:
                    await self._run_stages(run, execution_started)
        except asyncio.CancelledError:
            if run.id not in self._cancel_requested:
                await self._fail(
                    run,
                    "Прогон прерван остановкой сервера",
                    execution_started=execution_started,
                )
                raise
            run.status = RunStatus.CANCELLED
            run.error = "Прогон отменён участником"
            run.finished_at = self._rt.clock()
            run.latency_ms = max(0, round((time.perf_counter() - execution_started) * 1000))
            try:
                await self._repos.runs.update(run)
            except Exception:
                logger.exception("Не удалось сохранить отмену прогона %s", run.id)
            await self._publish(run, RunEventKind.DONE, run)
        except (PipelineError, BpmnFormatError, BpmnToolsError, StaleVersionError) as error:
            await self._fail(run, str(error), execution_started=execution_started)
        except TimeoutError:
            if scope is not None and scope.expired():
                await self._fail(run, DEADLINE_MESSAGE, execution_started=execution_started)
            else:
                logger.exception("Прогон %s: таймаут", run.id)
                await self._fail(run, _INTERNAL_ERROR, execution_started=execution_started)
        except Exception:
            logger.exception("Прогон %s упал", run.id)
            await self._fail(run, _INTERNAL_ERROR, execution_started=execution_started)

    async def _run_stages(self, run: Run, execution_started: float) -> None:
        run.status = RunStatus.RUNNING
        await self._repos.runs.update(run)
        state = _RunState()
        for stage in stages_for(run.mode):
            await self._enter(run, stage)
            await self._pace(stage)
            await self._perform(run, stage, state)
        # Пункты отмечаются до статуса `succeeded`: кто увидит успех (SSE или опрос), уже видит их.
        await self._record_progress(run)
        run.status = RunStatus.SUCCEEDED
        run.progress = 1.0
        run.finished_at = self._rt.clock()
        run.latency_ms = max(0, round((time.perf_counter() - execution_started) * 1000))
        await self._repos.runs.update(run)
        await self._repos.projects.touch(run.project_id, run.finished_at)

    async def _record_progress(self, run: Run) -> None:
        """Успешная сборка отмечает пункты чека тому, кто запустил прогон. Не бросает."""
        if self._progress is None or run.created_by is None or run.mode is not RunMode.BUILD:
            return
        try:
            await self._progress.record(run.created_by, ChecklistItem.DIAGRAM_BUILT)
            if await self._rebuilt_with_answers(run):
                await self._progress.record(run.created_by, ChecklistItem.DIAGRAM_REBUILT)
        except Exception:
            logger.exception("Прогон %s: не удалось отметить прогресс", run.id)

    async def _rebuilt_with_answers(self, run: Run) -> bool:
        """Схема уже была, и после неё появился ответ на вопрос — это перестроение."""
        versions = await self._repos.versions.list_by_project(run.project_id)  # новые — первыми
        created = next((v for v in versions if v.id == run.version_id), None)
        if created is None:
            return False
        previous = next((v for v in versions if v.number < created.number), None)
        if previous is None:
            return False
        sources = await self._repos.sources.list_by_project(run.project_id)
        # Ответы, пришедшие во время прогона, в эту сборку не вошли — не засчитываем.
        return any(
            s.kind is SourceKind.ANSWER and previous.created_at < s.created_at <= run.started_at
            for s in sources
        )

    async def _enter(self, run: Run, stage: RunStage) -> None:
        run.stage = stage
        run.progress = progress_at(run.mode, stage)
        await self._repos.runs.update(run)
        progress = StageProgress(
            stage=stage, label=stage_label(run.status, stage), progress=run.progress
        )
        await self._publish(run, RunEventKind.STAGE, progress)

    async def _perform(self, run: Run, stage: RunStage, state: _RunState) -> None:
        match stage:
            case RunStage.READING_SOURCES:
                state.context = await self._context(run.project_id)
                execution = (run.ir or {}).get("execution", {})
                expected = execution.get("base_version_id")
                if (
                    run.mode is RunMode.BUILD
                    and str(state.context.base_version_id) != str(expected)
                    and not (state.context.base_version_id is None and expected is None)
                ):
                    raise PipelineError(
                        "Голова схемы изменилась после запуска; повторите сборку от новой версии"
                    )
                state.context = replace(
                    state.context, replace_manual=bool(execution.get("replace_manual"))
                )
                run.warnings = list(state.context.warnings)
                await self._repos.runs.update(run)
            case RunStage.EXTRACTING:
                context = self._require(state)
                state.analysis = await self._model_call(
                    run,
                    stage="analyze",
                    request={"context": describe_context(context)},
                    call=lambda: self._pipeline.analyze(context),
                )
                run.analysis = _json_data(state.analysis)
                await self._repos.runs.update(run)
            case RunStage.RECONCILING:
                await self._reconcile(run, state)
            case RunStage.STRUCTURING:
                context = self._require(state)
                context = replace(
                    context, questions=await self._repos.questions.list_by_project(run.project_id)
                )
                state.context = context
                state.draft = await self._model_call(
                    run,
                    stage="structure",
                    request={
                        "context": describe_context(context),
                        "analysis": _json_data(state.analysis),
                    },
                    call=lambda: self._pipeline.structure(context, state.analysis),
                )
                if state.draft is None:
                    raise PipelineError("Пайплайн не вернул BPMN-черновик")
                execution = (run.ir or {}).get("execution", {})
                run.ir = {
                    "graph": state.draft.ir,
                    "execution": execution,
                    "manual_overrides": state.draft.manual_overrides,
                    "conflicts": state.draft.conflicts,
                }
                run.warnings.extend(state.draft.warnings)
                await self._repos.runs.update(run)
            case RunStage.VALIDATING:
                draft = state.draft
                if draft is None:
                    raise PipelineError("Схема не построена")
                errors = xsd_errors(draft.xml)
                if errors:
                    raise PipelineError(f"Схема не прошла проверку XSD: {errors[0]}")
                state.xml = draft.xml
            case RunStage.LAYOUT:
                await self._layout(run, state)

    @staticmethod
    def _require(state: _RunState) -> RunContext:
        if state.context is None:
            raise PipelineError("Контекст прогона не собран")
        return state.context

    async def _context(self, project_id: UUID) -> RunContext:
        async with self._repos.atomic() as repos:
            await repos.projects.lock(project_id)
            project = await get_project(repos, project_id)
            versions = await repos.versions.list_by_project(project_id)
            context = build_run_context(
                project=project,
                sources=await repos.sources.list_by_project(project_id),
                questions=await repos.questions.list_by_project(project_id),
                versions=versions,
                budget_chars=self._context_budget,
            )
            base = (
                versions[0]
                if versions and versions[0].run_id
                else next((v for v in versions if v.run_id), None)
            )
            if base and base.run_id:
                previous_run = await repos.runs.get(base.run_id)
                if previous_run and previous_run.ir:
                    context = replace(
                        context, manual_overrides=previous_run.ir.get("manual_overrides")
                    )
            return context

    async def _reconcile(self, run: Run, state: _RunState) -> None:
        context = self._require(state)
        changed = []
        resolved_now = 0
        warnings = list(state.analysis.warnings)
        async with self._repos.atomic() as repos:
            project = await repos.projects.lock(run.project_id)
            sources = await repos.sources.lock_by_project(run.project_id)
            current = await repos.questions.list_by_project(run.project_id)
            versions = await repos.versions.list_by_project(run.project_id)
            usable = [
                ContextSource(
                    id=s.id, kind=s.kind, title=s.title, content=s.content, created_at=s.created_at
                )
                for s in sources
                if s.active and s.status is SourceStatus.READY and s.content.strip()
            ]
            snapshot = (
                context.evidence_sources
                if context.evidence_sources is not None
                else context.sources
            )
            same_sources = {s.id: s for s in usable} == {s.id: s for s in snapshot}
            if context.source_snapshot_hash is not None:
                same_sources = (
                    same_sources and source_snapshot_hash(sources) == context.source_snapshot_hash
                )
            same_questions = {q.id: q for q in current} == {q.id: q for q in context.questions}
            same_diagram = (versions[0].xml if versions else None) == context.current_xml
            same_project = project is not None and project.title == context.project_title
            if not same_sources or not same_questions or not same_diagram or not same_project:
                warnings.append(
                    "Источники, вопросы или схема изменились во время анализа: сверка по прежнему "
                    "снимку не применена. Повторите анализ актуальных материалов."
                )
            else:
                before = {q.id: deepcopy(q) for q in current}
                outcome = reconcile(
                    current,
                    state.analysis,
                    snapshot,
                    project_id=run.project_id,
                    run_id=run.id,
                    now=self._rt.clock(),
                    new_id=self._rt.new_id,
                )
                warnings.extend(outcome.rejected)
                for question in outcome.changed:
                    previous = before[question.id]
                    # Даже изменение ответа без изменения статуса не затирается старым решением.
                    if not await repos.questions.apply_reconciled(
                        question,
                        expected_status=previous.status,
                        expected_updated_at=previous.updated_at,
                    ):
                        warnings.append(
                            f"{question.code}: вопрос изменён параллельно, сверка пропущена"
                        )
                        continue
                    changed.append(question)
                    resolved_now += int(question.status is QuestionStatus.RESOLVED)
                    reason = next(
                        (
                            u.reason
                            for u in state.analysis.question_updates
                            if u.code == question.code
                        ),
                        None,
                    )
                    if reason:
                        warnings.append(f"{question.code}: {reason}")
                for question in outcome.created:
                    await repos.questions.add(question)
                    changed.append(question)
            # Итог считает только реально сохранённые решения, включая CAS-отказы.
            actual = await repos.questions.list_by_project(run.project_id)
            run.summary = run_summary(actual, run_id=run.id, resolved_now=resolved_now)
        run.warnings = list(dict.fromkeys([*run.warnings, *warnings]))
        state.analysis.audit["application"] = {
            "sources_unchanged": same_sources,
            "questions_unchanged": same_questions,
            "diagram_unchanged": same_diagram,
            "project_unchanged": same_project,
            "applied_question_codes": [q.code for q in changed],
            "warnings": warnings,
        }
        run.analysis = _json_data(state.analysis)
        await self._repos.runs.update(run)
        for question in changed:
            await self._publish(run, RunEventKind.QUESTION, question)
        await self._publish(run, RunEventKind.SUMMARY, run.summary)

    async def _layout(self, run: Run, state: _RunState) -> None:
        if state.xml is None or state.draft is None:
            raise PipelineError("Схема не прошла проверку")
        xml = await self._tools.layout(state.xml)
        if state.context and state.context.current_xml and not state.context.replace_manual:
            xml = preserve_geometry(xml, state.context.current_xml) if state.draft.ir else xml
        lint = await self._tools.lint(xml)
        if state.draft.ir and any(issue.severity.value == "error" for issue in lint):
            raise PipelineError(
                "Схема не прошла полный линт: " + "; ".join(issue.message for issue in lint[:5])
            )
        if xsd_errors(xml):
            raise PipelineError("Раскладка вернула схему, не прошедшую XSD")
        if getattr(self._tools, "quality", "full") != "full":
            run.warnings.append(
                "Runtime bpmn-tools не подключён: проверен ограниченный набор правил"
            )
        warnings = getattr(self._tools, "warnings", None)
        if warnings:
            run.warnings.extend(warnings())
        execution = (run.ir or {}).get("execution", {})
        base = execution.get("base_version_id")
        async with self._repos.atomic() as repos:
            # Откат SQL не откатывает dataclass: результат переносим в живой Run только
            # после commit, иначе _fail может записать ссылку на несуществующую версию.
            staged = deepcopy(run)
            if await repos.projects.lock(run.project_id) is None:
                raise NotFoundError("Проект не найден")
            latest = await repos.versions.latest(run.project_id)
            if (str(latest.id) if latest else None) != base:
                raise StaleVersionError(
                    latest.id if latest else None, latest.number if latest else None
                )
            locked_sources = await repos.sources.lock_by_project(run.project_id)
            if state.context and (
                (
                    state.context.source_snapshot_hash is not None
                    and source_snapshot_hash(locked_sources) != state.context.source_snapshot_hash
                )
                or _source_snapshot(locked_sources)
                != _source_snapshot(state.context.evidence_sources or state.context.sources)
            ):
                raise PipelineError(
                    "Материалы проекта изменились во время сборки; "
                    "повторите её от обновлённых источников"
                )
            if state.context and _question_snapshot(
                await repos.questions.list_by_project(run.project_id)
            ) != _question_snapshot(state.context.questions):
                raise PipelineError("Ответы или допущения изменились во время сборки; повторите её")
            sources = {source.id: source for source in locked_sources}
            for citation in state.draft.trace.values():
                source = sources.get(citation.source_id)
                if (
                    source is None
                    or not source.active
                    or source.status is not SourceStatus.READY
                    or not quote_in_source(citation.quote, source.content)
                ):
                    raise PipelineError(
                        "Источник изменился во время сборки; "
                        "повторите её, чтобы обновить доказательства"
                    )
            graph_questions = await self._graph_questions(repos, staged, state.draft)
            version = await add_version(
                repos,
                self._rt,
                project_id=run.project_id,
                xml=xml,
                origin=VersionOrigin.GENERATED,
                lint=lint,
                trace=state.draft.trace,
                run_id=run.id,
                actor_email=run.actor_email,
                expected_base_version_id=UUID(base) if base else None,
                enforce_base=True,
            )
            staged.version_id = version.id
            staged.report = _json_data(version.report)
            await repos.runs.update(staged)
        run.summary = staged.summary
        run.version_id = staged.version_id
        run.report = staged.report
        await self._publish_graph_result(run, version, graph_questions)

    async def _publish_graph_result(
        self, run: Run, version: Version, questions: list[Question]
    ) -> None:
        for question in questions:
            await self._publish(run, RunEventKind.QUESTION, question)
        if questions and run.summary:
            await self._publish(run, RunEventKind.SUMMARY, run.summary)
        await self._publish(run, RunEventKind.VERSION, version)

    async def _graph_questions(
        self, repos: Repositories, run: Run, draft: DiagramDraft
    ) -> list[Question]:
        questions = await repos.questions.list_by_project(run.project_id)
        for question in questions:
            if question.code in draft.bindings:
                await repos.questions.bind_elements(question.id, draft.bindings[question.code])
        proposals = []
        for conflict in draft.conflicts:
            source = conflict.get("source")
            manual = _conflict_value(conflict["manual"], draft.ir or {})
            proposed = _conflict_value(conflict["proposed"], draft.ir or {})
            element_id = conflict["element_id"]
            proposals.append(
                NewQuestion(
                    kind=QuestionKind.CONFLICT,
                    severity=Severity.MAJOR,
                    text=(
                        f"Вы задали {manual}. В материалах предлагается {proposed}. "
                        "Какой вариант оставить?"
                    )[:1000],
                    assumption=f"Сохраняем ручное значение: {manual}"[:1000],
                    about=Quote(source_id=UUID(source["source_id"]), quote=source["quote"])
                    if source
                    else None,
                    element_ids=[element_id],
                )
            )
        if proposals:
            # Внешняя layout-транзакция уже держит project/source locks. Повторный
            # self._context открыл бы другую SQL-сессию и ждал бы собственную блокировку.
            context = build_run_context(
                project=await get_project(repos, run.project_id),
                sources=await repos.sources.list_by_project(run.project_id),
                questions=questions,
                versions=await repos.versions.list_by_project(run.project_id),
                budget_chars=self._context_budget,
            )
            outcome = reconcile(
                questions,
                AnalysisResult(new_questions=proposals),
                context.evidence_sources or context.sources,
                project_id=run.project_id,
                run_id=run.id,
                now=self._rt.clock(),
                new_id=self._rt.new_id,
            )
            for question in outcome.created:
                await repos.questions.add(question)
            resolved = run.summary.resolved if run.summary else 0
            run.summary = run_summary(
                await repos.questions.list_by_project(run.project_id),
                run_id=run.id,
                resolved_now=resolved,
            )
            return outcome.created

        return []

    async def _model_call(
        self,
        run: Run,
        *,
        stage: str,
        request: dict[str, Any],
        call: Callable[[], Awaitable[Any]],
    ) -> Any:
        """Вызов шага пайплайна с записью аудита: запрос, ответ или ошибка, задержка, токены."""
        started = time.perf_counter()
        response: Any = None
        failure: Exception | None = None
        with track_usage() as usage:
            try:
                response = await call()
            except Exception as error:
                failure = error
        # Токены известны только у провайдеров, которые их сообщают (mock — `null`).
        await self._repos.llm_calls.add(
            LlmCall(
                id=self._rt.new_id(),
                run_id=run.id,
                stage=stage,
                request=_json_data(request),
                response={"error": str(failure)} if failure else _json_data(response),
                tokens_in=usage.tokens_in if usage.requests else None,
                tokens_out=usage.tokens_out if usage.requests else None,
                latency_ms=max(0, round((time.perf_counter() - started) * 1000)),
            )
        )
        if failure is not None:
            raise failure
        return response

    async def _fail(self, run: Run, message: str, *, execution_started: float) -> None:
        run.status = RunStatus.FAILED
        run.error = message
        run.finished_at = self._rt.clock()
        run.latency_ms = max(0, round((time.perf_counter() - execution_started) * 1000))
        try:
            await self._repos.runs.update(run)
        except Exception:
            # Даже если БД недоступна, подписчик должен узнать об ошибке и закрыть поток.
            logger.exception("Не удалось сохранить ошибку прогона %s", run.id)
        finally:
            await self._publish(run, RunEventKind.ERROR, RunError(message=message))
            await self._publish(run, RunEventKind.DONE, run)

    async def _publish(self, run: Run, kind: RunEventKind, payload: Any) -> None:
        await self._events.publish(run.id, kind, payload)
        await self._publish_live(run)

    async def _publish_live(self, run: Run) -> None:
        if self._broadcast is None:
            return
        message: dict[str, object] = {
            "type": "run.changed",
            "run_id": str(run.id),
            "mode": run.mode.value,
            "status": run.status.value,
            "actor": run.actor_email,
            "stage": run.stage.value if run.stage else None,
            "progress": run.progress,
            "version_id": str(run.version_id) if run.version_id else None,
            "error": run.error,
        }
        try:
            await self._broadcast(run.project_id, message)
        except Exception:
            # Realtime is a best-effort projection; it must never fail or stop the durable run.
            logger.exception("Прогон %s: не удалось разослать realtime-событие", run.id)
