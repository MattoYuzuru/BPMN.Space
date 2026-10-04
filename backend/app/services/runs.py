"""Прогоны (RFC §5.1): запуск `202`, выполнение этапов в фоне, события для SSE.

Не больше `max_concurrent_runs` прогонов одновременно (остальные ждут в `queued`), по одному
активному прогону на проект (повторный запуск → 409). Каждый этап публикует `stage`;
сверка вопросов — `question` на каждый изменённый или новый вопрос и `summary`; сборка — `version`;
последним всегда идёт `done` (при ошибке ему предшествует `error`).
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from app.domain.analysis import AnalysisResult, DiagramDraft, RunContext
from app.domain.bpmn.document import BpmnFormatError
from app.domain.bpmn.xsd import xsd_errors
from app.domain.models import (
    LlmCall,
    Run,
    RunMode,
    RunStage,
    RunStatus,
    SourceKind,
    SourceStatus,
    VersionOrigin,
)
from app.domain.questions import reconcile
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
from app.infra.bpmn_tools import BpmnTools
from app.infra.events import RunEventBus
from app.infra.repositories.base import ActiveRunConflictError, Repositories
from app.infra.tasks import TaskSpawner
from app.ingest.context import build_run_context, describe_context
from app.llm.base import (
    DEADLINE_MESSAGE,
    PipelineError,
    ProcessPipeline,
    run_deadline,
    track_usage,
)
from app.services.common import Runtime, get_project, get_run
from app.services.errors import ConflictError, NotFoundError
from app.services.versions import add_version

logger = logging.getLogger(__name__)

type Pace = Callable[[RunStage], Awaitable[None]]


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
        self._limit = asyncio.Semaphore(max(max_concurrent, 1))
        # Этот lock ускоряет конфликт внутри процесса; уникальный индекс защищает между процессами.
        self._start_lock = asyncio.Lock()

    async def start(self, project_id: UUID, *, mode: RunMode) -> Run:
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
            now = self._rt.clock()
            run = Run(
                id=self._rt.new_id(),
                project_id=project_id,
                mode=mode,
                status=RunStatus.QUEUED,
                started_at=now,
                model=getattr(self._pipeline, "model_name", type(self._pipeline).__name__),
            )
            try:
                await repos.runs.add(run)
            except ActiveRunConflictError as error:
                raise ConflictError(
                    "По проекту уже идёт прогон — дождитесь его завершения"
                ) from error
            await repos.projects.touch(project_id, now)
        self._spawner.spawn(self._execute(run.id), name=f"run-{run.id}")
        return run

    async def get(self, run_id: UUID) -> Run:
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
            run = await self._repos.runs.get(run_id)
            if run is None:
                return
            try:
                await self._drive(run)
            finally:
                # Что бы ни случилось, подписчики SSE получают `done`: иначе поток висел бы вечно.
                # Если `done` уже опубликован, повтор игнорируется шиной.
                await self._events.publish(run.id, RunEventKind.DONE, run)

    async def _drive(self, run: Run) -> None:
        execution_started = time.perf_counter()
        deadline = self._deadline_sec if self._deadline_sec > 0 else None
        scope: asyncio.Timeout | None = None
        try:
            with run_deadline(deadline):
                async with asyncio.timeout(deadline) as scope:
                    await self._run_stages(run, execution_started)
        except asyncio.CancelledError:
            await self._fail(
                run, "Прогон прерван остановкой сервера", execution_started=execution_started
            )
            raise
        except (PipelineError, BpmnFormatError) as error:
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
        run.status = RunStatus.SUCCEEDED
        run.progress = 1.0
        run.finished_at = self._rt.clock()
        run.latency_ms = max(0, round((time.perf_counter() - execution_started) * 1000))
        await self._repos.runs.update(run)
        await self._repos.projects.touch(run.project_id, run.finished_at)

    async def _enter(self, run: Run, stage: RunStage) -> None:
        run.stage = stage
        run.progress = progress_at(run.mode, stage)
        await self._repos.runs.update(run)
        progress = StageProgress(
            stage=stage, label=stage_label(run.status, stage), progress=run.progress
        )
        await self._events.publish(run.id, RunEventKind.STAGE, progress)

    async def _perform(self, run: Run, stage: RunStage, state: _RunState) -> None:
        match stage:
            case RunStage.READING_SOURCES:
                state.context = await self._context(run.project_id)
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
                state.draft = await self._model_call(
                    run,
                    stage="structure",
                    request={
                        "context": describe_context(context),
                        "analysis": _json_data(state.analysis),
                    },
                    call=lambda: self._pipeline.structure(context, state.analysis),
                )
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
        project = await get_project(self._repos, project_id)
        return build_run_context(
            project=project,
            sources=await self._repos.sources.list_by_project(project_id),
            questions=await self._repos.questions.list_by_project(project_id),
            versions=await self._repos.versions.list_by_project(project_id),
            budget_chars=self._context_budget,
        )

    async def _reconcile(self, run: Run, state: _RunState) -> None:
        context = self._require(state)
        questions = await self._repos.questions.list_by_project(run.project_id)
        outcome = reconcile(
            questions,
            state.analysis,
            context.sources,
            project_id=run.project_id,
            run_id=run.id,
            now=self._rt.clock(),
            new_id=self._rt.new_id,
        )
        for reason in outcome.rejected:
            logger.info("Прогон %s: отклонено обновление вопроса — %s", run.id, reason)
        for question in outcome.changed:
            await self._repos.questions.update(question)
            await self._events.publish(run.id, RunEventKind.QUESTION, question)
        for question in outcome.created:
            await self._repos.questions.add(question)
            await self._events.publish(run.id, RunEventKind.QUESTION, question)
        run.summary = outcome.summary
        await self._repos.runs.update(run)
        await self._events.publish(run.id, RunEventKind.SUMMARY, outcome.summary)

    async def _layout(self, run: Run, state: _RunState) -> None:
        if state.xml is None or state.draft is None:
            raise PipelineError("Схема не прошла проверку")
        xml = await self._tools.layout(state.xml)
        version = await add_version(
            self._repos,
            self._rt,
            project_id=run.project_id,
            xml=xml,
            origin=VersionOrigin.GENERATED,
            lint=await self._tools.lint(xml),
            trace=state.draft.trace,
            run_id=run.id,
        )
        run.version_id = version.id
        run.report = _json_data(version.report)
        await self._repos.runs.update(run)
        await self._events.publish(run.id, RunEventKind.VERSION, version)

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
            await self._events.publish(run.id, RunEventKind.ERROR, RunError(message=message))
            await self._events.publish(run.id, RunEventKind.DONE, run)
