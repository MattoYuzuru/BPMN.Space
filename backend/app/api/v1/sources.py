"""Источники проекта и расшифровка голоса."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, File, Form, Response, UploadFile, status

from app.api.deps import ContainerDep
from app.api.schemas.common import errors
from app.api.schemas.projects import Transcription
from app.api.schemas.sources import Source, SourceTextCreate, SourceUpdate

router = APIRouter(tags=["sources"])


@router.post(
    "/projects/{project_id}/sources/text",
    status_code=status.HTTP_201_CREATED,
    responses=errors(404, 422),
)
async def create_text_source(
    project_id: UUID, body: SourceTextCreate, container: ContainerDep
) -> Source:
    """Текст или голосовая заметка (`kind=voice`) после проверки расшифровки аналитиком."""
    source = await container.sources.create_text(
        project_id,
        content=body.content,
        title=body.title,
        kind=body.kind,
        duration_sec=body.duration_sec,
    )
    return Source.model_validate(source)


@router.post(
    "/projects/{project_id}/sources/file",
    status_code=status.HTTP_201_CREATED,
    responses=errors(404, 413, 415, 422),
)
async def create_file_source(
    project_id: UUID,
    container: ContainerDep,
    background: BackgroundTasks,
    file: Annotated[UploadFile, File(description=".txt, .md, .docx или .pdf")],
    title: Annotated[str | None, Form(max_length=200)] = None,
) -> Source:
    """Документ. `.txt`/`.md` готовы сразу; `.docx`/`.pdf` приходят в `processing`
    и становятся `ready` или `failed` в фоне — обновляйте проект, пока есть `processing`."""
    data = await file.read()
    source, slow = await container.sources.create_file(
        project_id,
        file_name=file.filename or "document.txt",
        mime=file.content_type,
        data=data,
        title=title,
    )
    if slow:
        background.add_task(container.sources.process_file, source.id)
    return Source.model_validate(source)


@router.patch("/sources/{source_id}", responses=errors(404, 422))
async def update_source(source_id: UUID, body: SourceUpdate, container: ContainerDep) -> Source:
    """Поправить название или текст, включить или выключить источник."""
    source = await container.sources.update(
        source_id,
        title=body.title,
        content=body.content,
        active=body.active,
        fields=body.model_fields_set,
    )
    return Source.model_validate(source)


@router.delete(
    "/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT, responses=errors(404, 422)
)
async def delete_source(source_id: UUID, container: ContainerDep) -> Response:
    """Удалить источник. Удаление ответа возвращает отвеченный вопрос в `open`."""
    await container.sources.delete(source_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/transcriptions", tags=["transcriptions"], responses=errors(413, 415, 422))
async def transcribe(
    container: ContainerDep,
    file: Annotated[UploadFile, File(description="Аудио: webm/ogg (opus), wav или mp3")],
) -> Transcription:
    """Расшифровка голоса для правки перед сохранением (источник или ответ на вопрос)."""
    data = await file.read()
    transcript = await container.transcriptions.transcribe(data, mime=file.content_type)
    return Transcription.model_validate(transcript)
