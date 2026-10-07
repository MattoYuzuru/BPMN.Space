"""Источники проекта и расшифровка голоса."""

from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Request,
    Response,
    UploadFile,
    status,
)

from app.api.access import (
    ResourceKind,
    ensure_project_access,
    ensure_resource_access,
    require_account,
)
from app.api.auth import OptionalUserDep
from app.api.deps import ContainerDep
from app.api.limits import read_upload
from app.api.ratelimit import limit_expensive
from app.api.schemas.common import TranscriptionErrorResponse, errors
from app.api.schemas.onboarding import SampleAdd
from app.api.schemas.projects import Transcription
from app.api.schemas.sources import Source, SourceTextCreate, SourceUpdate
from app.domain.models import SourceKind
from app.domain.onboarding import ChecklistItem

router = APIRouter(tags=["sources"])


@router.post(
    "/projects/{project_id}/sources/text",
    status_code=status.HTTP_201_CREATED,
    responses=errors(401, 403, 404, 422),
)
async def create_text_source(
    project_id: UUID,
    body: SourceTextCreate,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> Source:
    """Текст или голосовая заметка (`kind=voice`) после проверки расшифровки аналитиком."""
    await ensure_project_access(request, container, project_id, user, write=True)
    source = await container.sources.create_text(
        project_id,
        content=body.content,
        title=body.title,
        kind=body.kind,
        duration_sec=body.duration_sec,
    )
    await container.onboarding.record(
        user.id if user else None,
        ChecklistItem.VOICE_ADDED
        if source.kind is SourceKind.VOICE
        else ChecklistItem.TEXT_SOURCE_ADDED,
    )
    return Source.model_validate(source)


@router.post(
    "/projects/{project_id}/sources/file",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_expensive)],
    responses=errors(401, 403, 404, 413, 415, 422, 429),
)
async def create_file_source(  # noqa: PLR0917 - multipart form fields are separate parameters
    project_id: UUID,
    request: Request,
    container: ContainerDep,
    background: BackgroundTasks,
    file: Annotated[UploadFile, File(description=".txt, .md, .csv, .docx или .pdf")],
    user: OptionalUserDep,
    title: Annotated[str | None, Form(max_length=200)] = None,
) -> Source:
    """Документ. `.txt`/`.md`/`.csv` готовы сразу; `.docx`/`.pdf` приходят в `processing`
    и становятся `ready` или `failed` в фоне — обновляйте проект, пока есть `processing`."""
    await ensure_project_access(request, container, project_id, user, write=True)
    data = await read_upload(file, subject="Файл", limit=container.settings.max_upload_bytes)
    source, slow = await container.sources.create_file(
        project_id,
        file_name=file.filename or "document.txt",
        mime=file.content_type,
        data=data,
        title=title,
    )
    if slow:
        background.add_task(container.sources.process_file, source.id)
    await container.onboarding.record(user.id if user else None, ChecklistItem.DOCUMENT_UPLOADED)
    return Source.model_validate(source)


@router.post(
    "/projects/{project_id}/sources/sample",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_expensive)],
    responses=errors(401, 403, 404, 422, 429),
)
async def create_sample_source(  # noqa: PLR0917 - FastAPI binds each parameter independently
    project_id: UUID,
    body: SampleAdd,
    request: Request,
    container: ContainerDep,
    background: BackgroundTasks,
    user: OptionalUserDep,
) -> Source:
    """Добавить учебный материал из `GET /samples` как обычный источник: документ проходит тот
    же разбор, что и `sources/file`, голосовая заметка сразу готова (`kind=voice`)."""
    await ensure_project_access(request, container, project_id, user, write=True)
    source, slow = await container.samples.add(project_id, body.sample_id)
    if slow:
        background.add_task(container.sources.process_file, source.id)
    await container.onboarding.record(
        user.id if user else None,
        ChecklistItem.VOICE_ADDED
        if source.kind is SourceKind.VOICE
        else ChecklistItem.DOCUMENT_UPLOADED,
    )
    return Source.model_validate(source)


@router.patch("/sources/{source_id}", responses=errors(401, 403, 404, 422))
async def update_source(
    source_id: UUID,
    body: SourceUpdate,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> Source:
    """Поправить название или текст, включить или выключить источник."""
    await ensure_resource_access(
        request, container, source_id, user, resource=ResourceKind.SOURCE, write=True
    )
    source = await container.sources.update(
        source_id,
        title=body.title,
        content=body.content,
        active=body.active,
        fields=body.model_fields_set,
    )
    return Source.model_validate(source)


@router.delete(
    "/sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=errors(401, 403, 404, 422),
)
async def delete_source(
    source_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> Response:
    """Удалить источник. Удаление ответа возвращает отвеченный вопрос в `open`."""
    await ensure_resource_access(
        request, container, source_id, user, resource=ResourceKind.SOURCE, write=True
    )
    await container.sources.delete(source_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/transcriptions",
    tags=["transcriptions"],
    dependencies=[Depends(limit_expensive)],
    responses={
        **errors(401, 413, 415, 422, 429),
        422: {
            "model": TranscriptionErrorResponse,
            "description": "Некорректная запись или речь не распознана",
        },
    },
)
async def transcribe(
    request: Request,
    container: ContainerDep,
    file: Annotated[UploadFile, File(description="Аудио: webm/ogg (opus), wav или mp3")],
    user: OptionalUserDep,
) -> Transcription:
    """Расшифровка голоса для правки перед сохранением (источник или ответ на вопрос)."""
    require_account(request, user)
    data = await read_upload(file, subject="Запись", limit=container.settings.max_audio_bytes)
    transcript = await container.transcriptions.transcribe(data, mime=file.content_type)
    return Transcription.model_validate(transcript)
