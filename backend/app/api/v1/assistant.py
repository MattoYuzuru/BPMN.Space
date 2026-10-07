"""Диалог с помощником по текущему проекту."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.access import ensure_project_access, require_account
from app.api.auth import OptionalUserDep
from app.api.deps import ContainerDep
from app.api.ratelimit import limit_expensive
from app.api.schemas.assistant import AssistantRequest, AssistantResponse, LocalAssistantRequest
from app.api.schemas.common import errors
from app.llm.base import PipelineError

router = APIRouter(tags=["assistant"])


@router.post(
    "/projects/{project_id}/assistant",
    response_model=AssistantResponse,
    dependencies=[Depends(limit_expensive)],
    responses=errors(401, 403, 404, 410, 422, 429, 502, 503),
)
async def ask_assistant(
    project_id: UUID,
    body: AssistantRequest,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> AssistantResponse:
    await ensure_project_access(request, container, project_id, user, write=False)
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="Введите вопрос помощнику")
    if container.assistant is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Помощник не подключён. Настройте LLM_PROVIDER и ключ провайдера в .env.",
        )
    try:
        answer = await container.assistant.reply(
            project_id,
            message=message,
            diagram_xml=body.diagram_xml,
            history=[turn.model_dump() for turn in body.history],
        )
    except PipelineError as error:
        raise HTTPException(status_code=502, detail=error.args[0]) from error
    return AssistantResponse(answer=answer)


@router.post(
    "/assistant/chat",
    response_model=AssistantResponse,
    dependencies=[Depends(limit_expensive)],
    responses=errors(401, 422, 429, 502, 503),
)
async def ask_about_local_draft(
    body: LocalAssistantRequest,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> AssistantResponse:
    require_account(request, user)
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="Введите вопрос помощнику")
    if container.assistant is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Помощник не подключён. Настройте LLM_PROVIDER и ключ провайдера в .env.",
        )
    try:
        answer = await container.assistant.reply_local(
            project_title=body.project_title,
            source=body.source,
            diagram_xml=body.diagram_xml,
            history=[turn.model_dump() for turn in body.history],
            message=message,
        )
    except PipelineError as error:
        raise HTTPException(status_code=502, detail=error.args[0]) from error
    return AssistantResponse(answer=answer)
