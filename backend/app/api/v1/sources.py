"""Источники проекта и расшифровка голоса."""

import re
from datetime import UTC, datetime
from email.utils import format_datetime, parsedate_to_datetime
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
from fastapi.responses import StreamingResponse

from app.api.access import (
    ApiScope,
    ResourceKind,
    ensure_project_access,
    ensure_resource_access,
    require_account,
    require_scope,
    require_token_scope,
)
from app.api.auth import OptionalUserDep
from app.api.deps import ContainerDep
from app.api.limits import read_upload
from app.api.ratelimit import limit_expensive
from app.api.schemas.common import (
    ToolUnavailableErrorResponse,
    TranscriptionErrorResponse,
    errors,
)
from app.api.schemas.onboarding import SampleAdd
from app.api.schemas.projects import Transcription
from app.api.schemas.sources import (
    MediaEstimate,
    MediaEstimateFrames,
    MediaEstimateRequest,
    MediaEstimateStt,
    MediaSegment,
    MoneyRange,
    Source,
    SourceSegments,
    SourceTextCreate,
    SourceUpdate,
)
from app.domain.models import SourceKind
from app.domain.onboarding import ChecklistItem
from app.ingest.frames import MediaProfile
from app.ingest.media import is_media
from app.services.media_estimate import MediaEstimate as MediaEstimateData
from app.services.media_estimate import estimate_media

router = APIRouter(tags=["sources"])


@router.post(
    "/projects/{project_id}/sources/text",
    dependencies=[require_scope(ApiScope.SOURCES_WRITE)],
    status_code=status.HTTP_201_CREATED,
    responses=errors(401, 403, 404, 410, 422),
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
    dependencies=[require_scope(ApiScope.SOURCES_WRITE), Depends(limit_expensive)],
    responses=errors(401, 403, 404, 410, 413, 415, 422, 429),
)
async def create_file_source(  # noqa: PLR0917 - multipart form fields are separate parameters
    project_id: UUID,
    request: Request,
    container: ContainerDep,
    background: BackgroundTasks,
    file: Annotated[
        UploadFile,
        File(
            description=(
                ".txt, .md, .csv, .docx, .xlsx, .pptx, .pdf или аудио/видео "
                "(.mp3 .wav .ogg .opus .m4a .flac .aac .webm .mp4 .mov .mkv)"
            )
        ),
    ],
    user: OptionalUserDep,
    title: Annotated[str | None, Form(max_length=200)] = None,
    media_profile: Annotated[MediaProfile, Form()] = MediaProfile.AUDIO,
) -> Source:
    """Документ или запись. `.txt`/`.md`/`.csv` готовы сразу; `.docx`/`.xlsx`/`.pptx`/`.pdf` и
    аудио/видео приходят в `processing` и становятся `ready` или `failed` в фоне — обновляйте
    проект, пока есть `processing`. Страницы PDF без текста дают `ready` с `warning`.
    Запись возвращается как исходный файл без текста; её расшифровка — отдельный источник
    `origin=derived` с `parent_id` записи (RFC-0006).
    Записи пишутся на диск потоком (лимит `MAX_MEDIA_BYTES`), документы — `MAX_UPLOAD_BYTES`."""
    await ensure_project_access(request, container, project_id, user, write=True)
    file_name = file.filename or "document.txt"
    if is_media(file_name):
        # Запись расшифровывает платный провайдер: по токену нужно ещё и право запусков.
        require_token_scope(request, ApiScope.RUNS_START)
        source = await container.sources.create_media(
            project_id, file_name=file_name, mime=file.content_type, read=file.read, title=title
        )
        slow = True
    else:
        data = await read_upload(file, subject="Файл", limit=container.settings.max_upload_bytes)
        source, slow = await container.sources.create_file(
            project_id, file_name=file_name, mime=file.content_type, data=data, title=title
        )
    if slow:
        # Ключи распознавания — инициатора загрузки (RFC-0006); гостю по ссылке — серверные.
        background.add_task(
            container.sources.process_file,
            source.id,
            initiator_id=user.id if user is not None else None,
            media_profile=media_profile.value,
        )
    await container.onboarding.record(user.id if user else None, ChecklistItem.DOCUMENT_UPLOADED)
    return Source.model_validate(source)


@router.post(
    "/projects/{project_id}/sources/sample",
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_scope(ApiScope.SOURCES_WRITE), Depends(limit_expensive)],
    responses=errors(401, 403, 404, 410, 422, 429),
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
        # Ключи распознавания — инициатора загрузки (RFC-0006); гостю по ссылке — серверные.
        background.add_task(
            container.sources.process_file,
            source.id,
            initiator_id=user.id if user is not None else None,
        )
    await container.onboarding.record(
        user.id if user else None,
        ChecklistItem.VOICE_ADDED
        if source.kind is SourceKind.VOICE
        else ChecklistItem.DOCUMENT_UPLOADED,
    )
    return Source.model_validate(source)


@router.patch(
    "/sources/{source_id}",
    dependencies=[require_scope(ApiScope.SOURCES_WRITE)],
    responses=errors(401, 403, 404, 410, 422),
)
async def update_source(
    source_id: UUID,
    body: SourceUpdate,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> Source:
    """Поправить название или текст, включить или выключить источник.

    Правка текста производного источника ставит `edited_by_human=true`; у записи с
    расшифровкой своего текста нет (422). Выключение записи выключает и её производные."""
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
    dependencies=[require_scope(ApiScope.SOURCES_DELETE)],
    status_code=status.HTTP_204_NO_CONTENT,
    responses=errors(401, 403, 404, 409, 410, 422),
)
async def delete_source(
    source_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> Response:
    """Удалить источник вместе с производными (`parent_id`). Удаление ответа возвращает
    отвеченный вопрос в `open`. Производный источник, который ещё `processing`, удалить
    нельзя (409): запись удаляется целиком или после окончания обработки."""
    await ensure_resource_access(
        request, container, source_id, user, resource=ResourceKind.SOURCE, write=True
    )
    await container.sources.delete(source_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/projects/{project_id}/sources/media/estimate",
    dependencies=[require_scope(ApiScope.PROJECTS_READ)],
    responses=errors(401, 403, 404, 410, 422),
)
async def estimate_media_source(
    project_id: UUID,
    body: MediaEstimateRequest,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> MediaEstimate:
    """Оценка обработки записи до загрузки: минуты STT, кадры и цена по каталогу цен.

    Профиль `audio` — только расшифровка, `sparse` — редкие кадры и описание экрана,
    `detailed` — частые кадры. Оценка не запускает обработку и не пишет в БД.
    """
    await ensure_project_access(request, container, project_id, user, write=False)
    data = estimate_media(
        duration_sec=body.duration_sec,
        media_profile=body.media_profile,
        has_video=body.has_video,
        vision_batch_size=container.settings.media_vision_batch_size,
        frame_max_cap=container.settings.media_frame_max_frames,
    )
    return _estimate_response(data)


@router.get(
    "/sources/{source_id}/media",
    dependencies=[require_scope(ApiScope.PROJECTS_READ)],
    responses=errors(401, 403, 404, 410, 416),
    response_class=StreamingResponse,
)
async def stream_source_media(
    source_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> Response:
    """Плеер: аудио или видео записи с поддержкой HTTP Range.

    `200` — весь файл, `206` — запрошенный диапазон (`Content-Range`), `416` — диапазон вне
    файла. `ETag` и `Last-Modified` дают кэш; доступ — владельцу и участникам проекта
    (и токену с правом чтения), посторонним — `404`, как и остальные чужие объекты.
    """
    await ensure_resource_access(
        request, container, source_id, user, resource=ResourceKind.SOURCE, write=False
    )
    info = await container.sources.media_file(source_id)
    headers = media_headers(info.size, info.etag, info.last_modified)
    if _not_modified(request, info.etag, info.last_modified):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    range_header = request.headers.get("range")
    if range_header is None:
        headers["Content-Length"] = str(info.size)
        return StreamingResponse(
            container.sources.read_media(source_id, start=0, length=info.size),
            media_type=info.mime,
            headers=headers,
        )
    parsed = parse_byte_range(range_header, info.size)
    if parsed is None:
        headers["Content-Range"] = f"bytes */{info.size}"
        return Response(status_code=_HTTP_RANGE_NOT_SATISFIABLE, headers=headers)
    start, end = parsed
    headers["Content-Range"] = f"bytes {start}-{end}/{info.size}"
    headers["Content-Length"] = str(end - start + 1)
    return StreamingResponse(
        container.sources.read_media(source_id, start=start, length=end - start + 1),
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type=info.mime,
        headers=headers,
    )


@router.head(
    "/sources/{source_id}/media",
    dependencies=[require_scope(ApiScope.PROJECTS_READ)],
    responses=errors(401, 403, 404, 410),
)
async def head_source_media(
    source_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> Response:
    """HEAD для плеера: те же метаданные и права, без тела — `200`/`304`/`404`/`416` не нужен."""
    await ensure_resource_access(
        request, container, source_id, user, resource=ResourceKind.SOURCE, write=False
    )
    info = await container.sources.media_file(source_id)
    headers = media_headers(info.size, info.etag, info.last_modified)
    if _not_modified(request, info.etag, info.last_modified):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    headers["Content-Length"] = str(info.size)
    return Response(status_code=status.HTTP_200_OK, headers=headers)


@router.get(
    "/sources/{source_id}/segments",
    dependencies=[require_scope(ApiScope.PROJECTS_READ)],
    responses=errors(401, 403, 404, 409, 410),
)
async def source_segments(
    source_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> SourceSegments:
    """Таймкоды расшифровки: перемотка плеера к цитате `[мм:сс]` и границы отрезков.

    Работает и для записи (берётся её расшифровка), и для самой расшифровки.
    """
    await ensure_resource_access(
        request, container, source_id, user, resource=ResourceKind.SOURCE, write=False
    )
    transcript, segments = await container.sources.media_segments(source_id)
    return SourceSegments(
        source_id=source_id,
        transcript_id=transcript.id,
        duration_sec=transcript.duration_sec,
        segments=[
            MediaSegment(start_sec=start, end_sec=end, text=text) for start, end, text in segments
        ],
    )


@router.post(
    "/sources/{source_id}/ocr",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[require_scope(ApiScope.SOURCES_WRITE), Depends(limit_expensive)],
    responses={
        **errors(401, 403, 404, 409, 410, 422, 429),
        503: {
            "model": ToolUnavailableErrorResponse,
            "description": "Модели с чтением PDF нет: страницы-сканы не распознаны",
        },
    },
)
async def retry_source_ocr(
    source_id: UUID,
    request: Request,
    container: ContainerDep,
    background: BackgroundTasks,
    user: OptionalUserDep,
) -> Source:
    """Повторить OCR страниц-сканов PDF (действие «Повторить» технического вопроса).

    Создаёт или перезапускает производный узел OCR; фоновая задача читает страницы моделью с
    поддержкой PDF. Готовые страницы не распознаются заново: узел накапливает текст.
    """
    await ensure_resource_access(
        request, container, source_id, user, resource=ResourceKind.SOURCE, write=True
    )
    # OCR — платная работа на ключе пользователя: токену нужно ещё право запусков.
    require_token_scope(request, ApiScope.RUNS_START)
    node = await container.sources.retry_ocr(
        source_id, initiator_id=user.id if user is not None else None
    )
    background.add_task(
        container.sources.process_ocr,
        source_id,
        node.id,
        initiator_id=user.id if user is not None else None,
    )
    return Source.model_validate(node)


@router.post(
    "/transcriptions",
    tags=["transcriptions"],
    dependencies=[require_scope(ApiScope.RUNS_START), Depends(limit_expensive)],
    responses={
        **errors(401, 413, 415, 422, 429),
        422: {
            "model": TranscriptionErrorResponse,
            "description": "Некорректная запись или речь не распознана",
        },
        503: {
            "model": ToolUnavailableErrorResponse,
            "description": "Нет рабочего ключа распознавания или провайдер не принял запись",
        },
    },
)
async def transcribe(
    request: Request,
    container: ContainerDep,
    file: Annotated[UploadFile, File(description="Аудио: webm/ogg (opus), wav или mp3")],
    user: OptionalUserDep,
) -> Transcription:
    """Расшифровка голоса для правки перед сохранением (источник или ответ на вопрос).

    У вошедшего пользователя — на его ключах распознавания (RFC-0006), иначе — серверный
    провайдер. Если рабочих ключей нет, `503` с причиной и структурным прогрессом."""
    caller_id = require_account(request, user)
    data = await read_upload(file, subject="Запись", limit=container.settings.max_audio_bytes)
    transcript = await container.transcriptions.transcribe(
        data, mime=file.content_type, user_id=caller_id
    )
    return Transcription.model_validate(transcript)


_RANGE = re.compile(r"^bytes=(?P<spec>\d*-\d*)$")
_HTTP_RANGE_NOT_SATISFIABLE = 416


def parse_byte_range(header: str, size: int) -> tuple[int, int] | None:  # noqa: PLR0911
    """Разбирает один HTTP Range (`bytes=a-b`, `bytes=a-`, `bytes=-n`).

    Несколько диапазонов за раз не поддержаны: плееру достаточно одного, а `416` честнее
    попытки отдать неверную границу. `None` — диапазон некорректен или вне файла.
    """
    if size <= 0:
        return None
    match = _RANGE.match(header.strip())
    if match is None:
        return None
    first, _, last = match.group("spec").partition("-")
    try:
        if not first:
            suffix = int(last)
            if suffix <= 0:
                return None
            return max(size - suffix, 0), size - 1
        start = int(first)
        if start < 0 or start >= size:
            return None
        end = int(last) if last else size - 1
    except ValueError:
        return None
    if end < start:
        return None
    return start, min(end, size - 1)


def media_headers(size: int, etag: str, last_modified: datetime) -> dict[str, str]:
    """Заголовки кэша и Range для медиаответа; размер отдаётся только для `200`."""
    del size  # Content-Length выставляет конкретный ответ: у `206` он другой
    moment = (
        last_modified if last_modified.tzinfo is not None else last_modified.replace(tzinfo=UTC)
    )
    return {
        "Accept-Ranges": "bytes",
        "ETag": etag,
        "Last-Modified": format_datetime(moment.astimezone(UTC), usegmt=True),
        "Cache-Control": "private, max-age=0, must-revalidate",
    }


def _not_modified(request: Request, etag: str, last_modified: datetime) -> bool:
    """`304` по `If-None-Match` и `If-Modified-Since` (дата без зоны считается UTC)."""
    if_none_match = request.headers.get("if-none-match")
    if if_none_match is not None:
        candidates = {value.strip() for value in if_none_match.split(",")}
        return etag in candidates or "*" in candidates
    if_modified_since = request.headers.get("if-modified-since")
    if if_modified_since is None:
        return False
    try:
        since = parsedate_to_datetime(if_modified_since)
    except (TypeError, ValueError):
        return False
    if since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    moment = (
        last_modified if last_modified.tzinfo is not None else last_modified.replace(tzinfo=UTC)
    )
    return moment <= since.astimezone(UTC)


def _estimate_response(data: MediaEstimateData) -> MediaEstimate:
    """Dataclass оценки → схема API: одна точка перевода для оценки до загрузки."""
    return MediaEstimate(
        duration_sec=data.duration_sec,
        media_profile=data.media_profile,
        media_profile_label=data.profile_label,
        stt=MediaEstimateStt(
            minutes=data.stt_minutes,
            cost_usd=MoneyRange(min_usd=data.stt_cost.min_usd, max_usd=data.stt_cost.max_usd),
        ),
        frames=MediaEstimateFrames(
            count_min=data.frames_min,
            count_max=data.frames_max,
            vision_requests=data.vision_requests,
            cost_usd=MoneyRange(min_usd=data.vision_cost.min_usd, max_usd=data.vision_cost.max_usd),
        ),
        summary_cost_usd=(
            MoneyRange(
                min_usd=data.summary_cost.min_usd,
                max_usd=data.summary_cost.max_usd,
            )
            if data.summary_cost.max_usd
            else None
        ),
        total_cost_usd=MoneyRange(min_usd=data.total_cost.min_usd, max_usd=data.total_cost.max_usd),
        priced_on=data.priced_on,
        note=data.note,
    )
