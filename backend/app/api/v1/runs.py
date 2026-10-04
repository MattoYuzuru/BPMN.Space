"""Прогоны и их SSE-поток."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Request, status
from sse_starlette import EventSourceResponse, ServerSentEvent

from app.api.access import ensure_project_access, ensure_resource_access
from app.api.auth import OptionalUserDep
from app.api.deps import ContainerDep
from app.api.schemas.common import ApiModel, errors
from app.api.schemas.questions import Question
from app.api.schemas.runs import (
    DoneEventData,
    ErrorEventData,
    QuestionEventData,
    Run,
    RunCreate,
    RunEvent,
    RunSummary,
    StageEventData,
    VersionEventData,
)
from app.api.schemas.versions import Version
from app.domain import models
from app.domain.runs import RunError, RunEventKind, StageProgress
from app.domain.runs import RunEvent as DomainRunEvent

router = APIRouter(tags=["runs"])
SSE_PING_SEC = 15


@router.post(
    "/projects/{project_id}/runs",
    status_code=status.HTTP_202_ACCEPTED,
    responses=errors(404, 409, 422),
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
    return Run.of(await container.runs.start(project_id, mode=body.mode))


@router.get("/runs/{run_id}", responses=errors(404, 422))
async def get_run(
    run_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> Run:
    await ensure_resource_access(request, container, run_id, user, resource="run", write=False)
    return Run.of(await container.runs.get(run_id))


def _event_data(event: DomainRunEvent) -> ApiModel:
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
        case RunEventKind.DONE if isinstance(payload, models.Run):
            return DoneEventData(run=Run.of(payload))
        case _ if isinstance(payload, RunError):
            return ErrorEventData(message=payload.message)
        case _:
            raise TypeError(f"Неизвестное событие прогона: {event.kind}")


@router.get(
    "/runs/{run_id}/events",
    response_class=EventSourceResponse,
    responses={
        200: {
            "description": "Поток SSE (`text/event-stream`); схема — одно сообщение",
            "content": {"text/event-stream": {"schema": {"$ref": "#/components/schemas/RunEvent"}}},
        },
        **errors(404, 422),
    },
)
async def run_events(
    run_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
    last_event_id: Annotated[str | None, Header(description="Продолжить после события")] = None,
) -> EventSourceResponse:
    """События прогона: `stage`, `question`, `summary`, `version`, `error`, `done`.
    Сначала приходит вся история прогона, затем новые события; поток закрывается после `done`."""
    await ensure_resource_access(request, container, run_id, user, resource="run", write=False)
    after = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0
    events = await container.runs.events(run_id, after=after)

    async def stream() -> AsyncIterator[ServerSentEvent]:
        async for event in events:
            yield ServerSentEvent(
                data=_event_data(event).model_dump_json(),
                event=event.kind.value,
                id=str(event.id),
            )

    return EventSourceResponse(stream(), ping=SSE_PING_SEC)


# Схема сообщения SSE попадает в components через этот список (см. app/main.py).
OPENAPI_EXTRA_MODELS: tuple[type[ApiModel] | type[RunEvent], ...] = (RunEvent,)
