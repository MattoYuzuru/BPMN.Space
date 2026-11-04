"""Прогоны и их SSE-поток."""

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from sse_starlette import EventSourceResponse, ServerSentEvent

from app.api.access import (
    ApiScope,
    ResourceKind,
    ensure_project_access,
    ensure_resource_access,
    has_stream_project_access,
    require_scope,
)
from app.api.auth import OptionalUserDep, OptionalUserStreamDep
from app.api.deps import ContainerDep
from app.api.ratelimit import limit_expensive
from app.api.schemas.common import ApiModel, errors
from app.api.schemas.estimate import RunEstimate, RunEstimateRequest
from app.api.schemas.questions import Question
from app.api.schemas.runs import (
    DoneEventData,
    ErrorEventData,
    QuestionEventData,
    Run,
    RunCost,
    RunCreate,
    RunEvent,
    RunSummary,
    StageEventData,
    VersionEventData,
)
from app.api.schemas.versions import Version
from app.domain import models
from app.domain.runs import RunCost as DomainRunCost
from app.domain.runs import RunError, RunEventKind, StageProgress
from app.domain.runs import RunEvent as DomainRunEvent

router = APIRouter(tags=["runs"])
SSE_PING_SEC = 15
ACCESS_RECHECK_SEC = 30


@router.post(
    "/projects/{project_id}/runs",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[require_scope(ApiScope.RUNS_START), Depends(limit_expensive)],
    responses=errors(401, 403, 404, 409, 410, 422, 429),
)
async def start_run(
    project_id: UUID,
    body: RunCreate,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> Run:
    """Запустить прогон в фоне. Прогресс — `GET /runs/{id}/events` (SSE).
    Если по проекту уже идёт прогон или нет источников — 409."""
    await ensure_project_access(request, container, project_id, user, write=True)
    return Run.of(
        await container.runs.start(
            project_id,
            mode=body.mode,
            base_version_id=body.base_version_id,
            replace_manual=body.replace_manual,
            credential_id=body.credential_id,
            model=body.model,
            profile=body.profile.to_domain() if body.profile else None,
            created_by=user.id if user else None,
            actor_email=user.email if user else None,
        )
    )


@router.post(
    "/projects/{project_id}/runs/estimate",
    dependencies=[require_scope(ApiScope.PROJECTS_READ), Depends(limit_expensive)],
    responses=errors(401, 403, 404, 410, 422, 429, 503),
)
async def estimate_run(
    project_id: UUID,
    body: RunEstimateRequest,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> RunEstimate:
    """Оценить прогон до запуска: запросы, токены, деньги и длительность диапазоном.

    Профиль и модель — те же, что у запуска; ключ пользователя нужен только для бесплатного
    `count_tokens` Anthropic. При неизвестных ценах модели `complete=false`, а `cost=null`.
    """
    await ensure_project_access(request, container, project_id, user, write=False)
    estimate = await container.estimate.estimate(
        project_id,
        mode=body.mode,
        created_by=user.id if user else None,
        credential_id=body.credential_id,
        model=body.model,
        profile=body.profile.to_domain() if body.profile else None,
    )
    return RunEstimate.of(estimate, model=estimate.model, provider=estimate.provider)


@router.get(
    "/runs/{run_id}",
    dependencies=[require_scope(ApiScope.PROJECTS_READ)],
    responses=errors(401, 404, 410, 422),
)
async def get_run(
    run_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> Run:
    await ensure_resource_access(
        request, container, run_id, user, resource=ResourceKind.RUN, write=False
    )
    run = await container.runs.get(run_id)
    return Run.of(run, cost=await container.runs.cost(run_id))


@router.post(
    "/runs/{run_id}/cancel",
    dependencies=[require_scope(ApiScope.RUNS_START)],
    responses=errors(401, 403, 404, 410, 422),
)
async def cancel_run(
    run_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> Run:
    """Остановить общий прогон проекта. Доступно владельцу и редактору; viewer — только чтение."""
    await ensure_resource_access(
        request, container, run_id, user, resource=ResourceKind.RUN, write=True
    )
    run = await container.runs.cancel(run_id)
    return Run.of(run, cost=await container.runs.cost(run_id))


@router.post(
    "/runs/{run_id}/resume",
    dependencies=[require_scope(ApiScope.RUNS_START)],
    responses=errors(401, 403, 404, 409, 410, 422),
)
async def resume_run(
    run_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> Run:
    """Продолжить прогон, ждущий действия по техническому вопросу (`waiting` → `queued`).

    Открытые блокирующие технические вопросы этого прогона закрываются как принятые без
    действия; работа начинается заново с первого этапа, бюджет считает всё потраченное.
    """
    await ensure_resource_access(
        request, container, run_id, user, resource=ResourceKind.RUN, write=True
    )
    run = await container.runs.resume_waiting(run_id)
    return Run.of(run, cost=await container.runs.cost(run_id))


def _event_data(  # noqa: PLR0911 — по одному возврату на тип SSE-события
    event: DomainRunEvent, *, cost: DomainRunCost | None = None
) -> ApiModel:
    payload = event.payload
    match event.kind:
        case RunEventKind.STAGE if isinstance(payload, StageProgress):
            return StageEventData(
                stage=payload.stage, label=payload.label, progress=payload.progress
            )
        case RunEventKind.QUESTION if isinstance(payload, models.Question):
            return QuestionEventData(question=Question.model_validate(payload))
        case RunEventKind.SUMMARY if isinstance(payload, models.RunSummary):
            return RunSummary.model_validate(payload)
        case RunEventKind.VERSION if isinstance(payload, models.Version):
            return VersionEventData(version=Version.model_validate(payload))
        case RunEventKind.USAGE if isinstance(payload, DomainRunCost):
            return RunCost.of(payload)
        case RunEventKind.DONE if isinstance(payload, models.Run):
            return DoneEventData(run=Run.of(payload, cost=cost))
        case _ if isinstance(payload, RunError):
            return ErrorEventData(message=payload.message)
        case _:
            raise TypeError(f"Неизвестное событие прогона: {event.kind}")


@router.get(
    "/runs/{run_id}/events",
    dependencies=[require_scope(ApiScope.PROJECTS_READ)],
    response_class=EventSourceResponse,
    responses={
        200: {
            "description": "Поток SSE (`text/event-stream`); схема — одно сообщение",
            "content": {"text/event-stream": {"schema": {"$ref": "#/components/schemas/RunEvent"}}},
        },
        **errors(401, 404, 410, 422),
    },
)
async def run_events(
    run_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserStreamDep,
    last_event_id: Annotated[str | None, Header(description="Продолжить после события")] = None,
) -> EventSourceResponse:
    """События прогона: `stage`, `question`, `summary`, `version`, `error`, `done`.
    Сначала приходит вся история прогона, затем новые события; поток закрывается после `done`."""
    await ensure_resource_access(
        request, container, run_id, user, resource=ResourceKind.RUN, write=False
    )
    after = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0
    events = await container.runs.events(run_id, after=after)
    project_id = (await container.runs.get(run_id)).project_id

    async def stream() -> AsyncIterator[ServerSentEvent]:
        async def next_event() -> DomainRunEvent:
            return await anext(events)

        pending: asyncio.Task[DomainRunEvent] | None = None
        try:
            while True:
                if pending is None:
                    pending = asyncio.create_task(next_event())
                done, _ = await asyncio.wait({pending}, timeout=ACCESS_RECHECK_SEC)
                if not await has_stream_project_access(request, container, project_id, user):
                    return
                if not done:
                    continue
                try:
                    event = pending.result()
                except StopAsyncIteration:
                    return
                pending = None
                cost = (
                    await container.runs.cost(run_id) if event.kind is RunEventKind.DONE else None
                )
                yield ServerSentEvent(
                    data=_event_data(event, cost=cost).model_dump_json(),
                    event=event.kind.value,
                    id=str(event.id),
                )
        finally:
            if pending is not None:
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            close = getattr(events, "aclose", None)
            if close is not None:
                await close()

    return EventSourceResponse(stream(), ping=SSE_PING_SEC)


# Схема сообщения SSE попадает в components через этот список (см. app/main.py).
OPENAPI_EXTRA_MODELS: tuple[type[ApiModel] | type[RunEvent], ...] = (RunEvent,)
