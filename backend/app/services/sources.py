"""Сценарии источников: текст и расшифровка голоса, загрузка файла, правка, выключение, удаление."""

import asyncio
import hashlib
import logging
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any
from uuid import UUID

from app.domain import questions as question_rules
from app.domain.capabilities import (
    CapabilityIncident,
    CapabilityIncidentSink,
    CapabilityOutcome,
)
from app.domain.models import (
    MediaInfo,
    Source,
    SourceDerivation,
    SourceKind,
    SourceOrigin,
    SourceStatus,
    SourceTrust,
)
from app.domain.projects import default_source_title
from app.domain.sources import (
    SPEECH_TO_TEXT,
    TRANSCRIPT_TITLE,
    derivation_frame_keys,
    descendants,
    transcript_segments,
)
from app.infra.repositories.base import Repositories
from app.infra.storage import ChunkReader, FileStorage, UploadTooLargeError
from app.ingest.frames import frame_profile
from app.ingest.media import (
    MEDIA_EXTENSIONS,
    MediaError,
    MediaJob,
    MediaRoutingError,
    MediaTranscriber,
    is_media,
)
from app.ingest.parsers import (
    SUPPORTED_EXTENSIONS,
    DocumentParseError,
    DocumentParser,
    UnsupportedFormatError,
    detect_format,
    is_slow,
)
from app.ingest.stt import NoSpeechError, SpeechToText
from app.services.common import Runtime, get_project, get_source, too_large, touch_project
from app.services.errors import (
    ConflictError,
    InvalidInputError,
    NotFoundError,
    ToolUnavailableError,
    UnavailableError,
    UnsupportedMediaError,
)
from app.services.media_derivation import MediaDerivationService

logger = logging.getLogger(__name__)

# Возможность OCR (RFC-0006): производный узел со страницами-сканами.
OCR_CAPABILITY = "ocr"

MAX_SOURCE_TITLE = 200
TRANSCRIPT_MISSING = "Расшифровка записи удалена до окончания обработки. Загрузите запись заново"

_MEDIA_CHUNK = 1024 * 1024
# Запасной Content-Type, если браузер не прислал MIME при загрузке: по расширению файла.
_MEDIA_MIME_BY_SUFFIX = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".m4a": "audio/mp4",
    ".flac": "audio/flac",
    ".aac": "audio/aac",
    ".webm": "video/webm",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
}


@dataclass(frozen=True, slots=True)
class MediaFileInfo:
    """Метаданные медиафайла для `GET /sources/{id}/media` (HTTP Range и кэш)."""

    size: int
    mime: str
    etag: str
    last_modified: datetime


def _format_duration(seconds: float) -> str:
    total = round(seconds)
    return f"{total // 60}:{total % 60:02d}"


async def _ensure_parent(repos: Repositories, source: Source, batch: Sequence[Source]) -> None:
    """Родитель производного источника — существующий источник того же проекта.

    В PostgreSQL это же гарантирует составной FK `(parent_id, project_id)`; проверка здесь
    даёт понятную ошибку и защищает in-memory режим.
    """
    if source.parent_id is None:
        return
    if source.parent_id == source.id:
        raise InvalidInputError("Источник не может быть родителем самого себя")
    parent = next((item for item in batch if item.id == source.parent_id), None)
    parent = parent or await repos.sources.get(source.parent_id)
    if parent is None or parent.project_id != source.project_id:
        raise InvalidInputError("Родительский источник не найден в этом проекте")


class SourceService:
    def __init__(
        self,
        repos: Repositories,
        *,
        parser: DocumentParser,
        storage: FileStorage,
        runtime: Runtime,
        max_text_chars: int,
        max_upload_bytes: int,
        parse_delay_sec: float,
        media: MediaTranscriber | None = None,
        stt_for_user: Callable[[UUID | None], SpeechToText] | None = None,
        incident_sink: CapabilityIncidentSink | None = None,
        derivations: MediaDerivationService | None = None,
        max_media_bytes: int = 500 * 1024 * 1024,
    ) -> None:
        self._repos = repos
        self._parser = parser
        self._storage = storage
        self._rt = runtime
        self._max_text = max_text_chars
        self._max_upload = max_upload_bytes
        self._parse_delay = parse_delay_sec
        self._media = media
        # Ключи инициатора загрузки (RFC-0006); None — серверный провайдер.
        self._stt_for_user = stt_for_user
        # Мягкая стыковка с техническими вопросами волны 2B: приёмник необязателен.
        self._incident_sink = incident_sink
        # OCR сканов и производные узлы видео (RFC-0006, шаги 4–5); необязателен в тестах.
        self._derivations = derivations
        self._max_media = max_media_bytes

    def _clean_content(self, content: str) -> str:
        content = content.strip()
        if not content:
            raise InvalidInputError("Текст источника не может быть пустым")
        if len(content) > self._max_text:
            raise InvalidInputError(f"Текст длиннее {self._max_text} символов")
        return content

    @staticmethod
    def _clean_title(title: str | None) -> str | None:
        if title is None:
            return None
        title = " ".join(title.split())
        if len(title) > MAX_SOURCE_TITLE:
            raise InvalidInputError(f"Название длиннее {MAX_SOURCE_TITLE} символов")
        return title or None

    async def list(self, project_id: UUID) -> list[Source]:
        """Источники проекта по возрастанию `created_at` — без XML и производных вычислений."""
        await get_project(self._repos, project_id)
        return await self._repos.sources.list_by_project(project_id)

    async def get(self, source_id: UUID) -> Source:
        return await get_source(self._repos, source_id)

    async def create_text(
        self,
        project_id: UUID,
        *,
        content: str,
        title: str | None,
        kind: SourceKind,
        duration_sec: float | None,
        origin: SourceOrigin = SourceOrigin.USER,
        trust: SourceTrust = SourceTrust.PRIMARY,
        derivation: SourceDerivation | None = None,
    ) -> Source:
        """Текст или проверенная аналитиком расшифровка голосовой заметки (`kind=voice`).

        `origin=agent` и `trust=agent` ставит MCP-сервер (RFC-0007): материал принёс внешний
        агент владельца токена, а не человек. `derivation` хранит провенанс агента (токен, ссылка).
        """
        if kind not in {SourceKind.TEXT, SourceKind.VOICE}:
            raise InvalidInputError("Через этот метод добавляется только текст или голос")
        await get_project(self._repos, project_id)
        content = self._clean_content(content)
        if kind is SourceKind.VOICE:
            fallback = "Голосовая заметка"
            if duration_sec:
                fallback = f"{fallback}, {_format_duration(duration_sec)}"
        else:
            fallback = default_source_title(content)
        now = self._rt.clock()
        source = Source(
            id=self._rt.new_id(),
            project_id=project_id,
            kind=kind,
            title=self._clean_title(title) or fallback,
            content=content,
            status=SourceStatus.READY,
            active=True,
            created_at=now,
            duration_sec=duration_sec if kind is SourceKind.VOICE else None,
            origin=origin,
            trust=trust,
            derivation=derivation,
        )
        async with self._repos.atomic() as repos:
            await repos.projects.lock(project_id)
            await get_project(repos, project_id)
            await repos.sources.add(source)
            await touch_project(repos, project_id, now)
        return source

    async def create_file(
        self,
        project_id: UUID,
        *,
        file_name: str,
        mime: str | None,
        data: bytes,
        title: str | None,
    ) -> tuple[Source, bool]:
        """Сохраняет документ. Возвращает источник и флаг «дочитать в фоне» (`process_file`).

        `.txt`/`.md`/`.csv` разбираются сразу (`ready`), `.docx`/`.xlsx`/`.pptx`/`.pdf` — в фоне
        (`processing`). Аудио и видео — отдельный потоковый путь `create_media`.
        """
        await get_project(self._repos, project_id)
        if is_media(file_name):
            raise InvalidInputError("Аудио и видео загружаются потоком: используйте create_media")
        fmt = self._detect(file_name)
        if not data:
            raise InvalidInputError("Файл пустой")
        if len(data) > self._max_upload:
            raise too_large("Файл", self._max_upload)

        now = self._rt.clock()
        key = await self._storage.save(project_id=project_id, file_name=file_name, data=data)
        source = Source(
            id=self._rt.new_id(),
            project_id=project_id,
            kind=SourceKind.FILE,
            title=self._clean_title(title) or file_name,
            content="",
            status=SourceStatus.PROCESSING,
            active=True,
            created_at=now,
            file_name=file_name,
            mime=mime,
            size_bytes=len(data),
            file_key=key,
        )
        background = is_slow(fmt)
        if not background:
            for name, value in (await self._parse_changes(file_name=file_name, data=data)).items():
                setattr(source, name, value)
        await self._add_source(source, project_id=project_id, key=key, now=now)
        return source, background

    async def _add_source(
        self,
        source: Source,
        *,
        project_id: UUID,
        key: str,
        now: datetime,
        derived: Sequence[Source] = (),
    ) -> None:
        try:
            async with self._repos.atomic() as repos:
                await repos.projects.lock(project_id)
                await get_project(repos, project_id)
                batch = [source, *derived]
                for item in batch:
                    await _ensure_parent(repos, item, batch)
                    await repos.sources.add(item)
                await touch_project(repos, project_id, now)
        except NotFoundError:
            # Владелец мог удалить проект, пока файл сохранялся или разбирался.
            # До вставки источника не дошли: этот blob уже никому не принадлежит.
            try:
                await self._storage.delete(key)
            except OSError:
                logger.warning("Не удалён файл %s после удаления проекта во время загрузки", key)
            raise

    @staticmethod
    def _detect(file_name: str):
        try:
            return detect_format(file_name)
        except UnsupportedFormatError:
            allowed = ", ".join((*SUPPORTED_EXTENSIONS, *MEDIA_EXTENSIONS))
            raise UnsupportedMediaError(f"Формат не поддерживается. Загрузите {allowed}") from None

    async def create_media(
        self,
        project_id: UUID,
        *,
        file_name: str,
        mime: str | None,
        read: ChunkReader,
        title: str | None,
    ) -> Source:
        """Аудио или видео: файл пишется на диск потоком, расшифровка идёт в фоне (`process_file`).

        Создаются два узла дерева (RFC-0006): исходный файл (`origin=user`, без текста для
        модели) и производная «Расшифровка» (`origin=derived`, `trust=extracted`). Оба сразу
        `processing`; после ffmpeg и STT расшифровка станет `ready` (текст с `[мм:сс]`), а
        запись — `ready` с длительностью и дорожками, либо оба `failed` с одной причиной.
        Возвращается исходный файл.
        """
        await get_project(self._repos, project_id)
        if self._media is None:
            raise UnsupportedMediaError("Обработка аудио и видео не включена на сервере")
        try:
            key, size = await self._storage.save_stream(
                project_id=project_id, file_name=file_name, read=read, limit=self._max_media
            )
        except UploadTooLargeError:
            raise too_large("Файл", self._max_media) from None
        if size == 0:
            await self._storage.delete(key)
            raise InvalidInputError("Файл пустой")
        now = self._rt.clock()
        source = Source(
            id=self._rt.new_id(),
            project_id=project_id,
            kind=SourceKind.FILE,
            title=self._clean_title(title) or file_name,
            content="",
            status=SourceStatus.PROCESSING,
            active=True,
            created_at=now,
            file_name=file_name,
            mime=mime,
            size_bytes=size,
            file_key=key,
        )
        transcript = Source(
            id=self._rt.new_id(),
            project_id=project_id,
            kind=SourceKind.TEXT,
            title=f"{TRANSCRIPT_TITLE}: {source.title}"[:MAX_SOURCE_TITLE],
            content="",
            status=SourceStatus.PROCESSING,
            active=True,
            created_at=now,
            origin=SourceOrigin.DERIVED,
            parent_id=source.id,
            trust=SourceTrust.EXTRACTED,
            derivation=SourceDerivation(
                capability=SPEECH_TO_TEXT,
                provider=self._media.provider,
                model=self._media.model,
                params=self._media.params(),
                created_at=now,
            ),
        )
        await self._add_source(
            source, project_id=project_id, key=key, now=now, derived=[transcript]
        )
        return source

    async def _media_changes(
        self,
        source: Source,
        transcript: Source | None,
        *,
        initiator_id: UUID | None,
    ) -> tuple[dict[str, Any], dict[str, Any], CapabilityOutcome | None]:
        """Изменения записи и её расшифровки по итогу ffprobe/ffmpeg/STT.

        Сбой виден на обоих узлах с одной причиной; дорожки записи сохраняются, если ffprobe
        успел их прочитать. Обработка идёт на ключах инициатора загрузки (RFC-0006), серверный
        провайдер — запасной путь. Структурный результат отказа маршрутизации возвращается третьим
        элементом: из него волна технических вопросов сделает вопрос, а пока он виден в
        `derivation.params.routing` и в понятном тексте ошибки.
        """
        job = MediaJob()
        routing: CapabilityOutcome | None = None

        def failed(error: str) -> tuple[dict[str, Any], dict[str, Any]]:
            parent: dict[str, Any] = {"status": SourceStatus.FAILED, "error": error}
            if (probe := job.probe) is not None:
                parent["media"] = MediaInfo(has_audio=probe.has_audio, has_video=probe.has_video)
                parent["duration_sec"] = probe.duration_sec
            child: dict[str, Any] = {"status": SourceStatus.FAILED, "error": error}
            if routing is not None:
                coverage = self._coverage_warning(routing)
                if coverage is not None:
                    parent["warning"] = coverage
                child["derivation"] = self._routing_derivation(transcript, routing)
            return parent, child

        if self._media is None or not source.file_key:
            parent, child = failed("Обработка аудио и видео не включена")
            return parent, child, routing
        engine = self._stt_for_user(initiator_id) if self._stt_for_user is not None else None
        try:
            async with self._storage.local_file(source.file_key) as path:
                result = await self._media.transcribe(path, job=job, stt=engine)
        except MediaRoutingError as error:
            routing = error.outcome
            parent, child = failed(str(error))
            return parent, child, routing
        except MediaError as error:
            parent, child = failed(str(error))
            return parent, child, routing
        except NoSpeechError:
            parent, child = failed("В записи не найдено речи")
            return parent, child, routing
        if len(result.text) > self._max_text:
            parent, child = failed(
                f"Расшифровка превышает лимит {self._max_text} символов. "
                "Разделите запись на части и загрузите их отдельно"
            )
            return parent, child, routing
        probe = job.probe
        media = MediaInfo(
            has_audio=probe.has_audio if probe else None,
            has_video=probe.has_video if probe else None,
        )
        parent = {
            "status": SourceStatus.READY,
            "error": None,
            "duration_sec": result.duration_sec,
            "media": media,
        }
        child: dict[str, Any] = {
            "status": SourceStatus.READY,
            "content": result.text,
            "error": None,
            "duration_sec": result.duration_sec,
        }
        if transcript is not None and transcript.derivation is not None:
            child["derivation"] = replace(
                transcript.derivation,
                provider=job.provider or transcript.derivation.provider,
                model=job.model or transcript.derivation.model,
                credential_id=job.credential_id or transcript.derivation.credential_id,
                cost_usd=job.cost_usd
                if job.cost_usd is not None
                else transcript.derivation.cost_usd,
                params={
                    **transcript.derivation.params,
                    "duration_sec": result.duration_sec,
                    "minutes": round(result.duration_sec / 60, 2),
                    "language": result.language,
                },
            )
        return parent, child, routing

    @staticmethod
    def _coverage_warning(routing: CapabilityOutcome) -> str | None:
        """Предупреждение о неполной обработке: что покрыто и что осталось.

        Пишется всегда, когда маршрутизатор знает хотя бы один из отрезков, — независимо от
        того, успел ли завершиться хотя бы один сегмент до отказа. Если покрытых сегментов нет,
        `done` пуст, и предупреждение честно говорит, что не обработана вся запись.
        """
        parts: list[str] = []
        if routing.done:
            parts.append(f"Обработано {routing.done}")
        if routing.remaining:
            parts.append(f"не обработано {routing.remaining}")
        return ", ".join(parts) if parts else None

    @staticmethod
    def _routing_derivation(
        transcript: Source | None, routing: CapabilityOutcome
    ) -> SourceDerivation | None:
        """Производная расшифровки с причиной отказа — для настроек и технического вопроса."""
        if transcript is None or transcript.derivation is None:
            return None
        return replace(
            transcript.derivation,
            provider=routing.provider or transcript.derivation.provider,
            credential_id=routing.credential_id or transcript.derivation.credential_id,
            params={**transcript.derivation.params, "routing": routing.to_json()},
        )

    async def _report_incident(self, source: Source, routing: CapabilityOutcome) -> None:
        """Мягкая стыковка с техническими вопросами (RFC-0006 шаг 2): приёмник необязателен."""
        sink = self._incident_sink
        if sink is None:
            return
        incident = CapabilityIncident(
            project_id=source.project_id,
            source_id=source.id,
            capability=routing.capability,
            status=routing.status,
            reason=routing.reason,
            message=routing.message or "Возможность недоступна",
            done=routing.done,
            remaining=routing.remaining,
            alternatives=routing.alternatives,
            derivation=routing.to_json(),
        )
        try:
            await sink.report(incident)
        except Exception:
            logger.exception("Не удалось передать отказ инструмента в технические вопросы")

    async def _process_media(
        self,
        source: Source,
        *,
        initiator_id: UUID | None = None,
        media_profile: str | None = None,
    ) -> None:
        siblings = await self._repos.sources.list_by_project(source.project_id)
        transcript = next(
            (
                s
                for s in siblings
                if s.parent_id == source.id
                and s.derivation is not None
                and s.derivation.capability == SPEECH_TO_TEXT
            ),
            None,
        )
        if transcript is None:
            # Расшифровки нет — распознавать некуда: не тратим STT, запись помечается сбоем.
            parent = {"status": SourceStatus.FAILED, "error": TRANSCRIPT_MISSING}
            async with self._repos.atomic() as repos:
                await repos.projects.lock(source.project_id)
                await repos.sources.patch(source.id, parent, only_status=SourceStatus.PROCESSING)
            return
        routing: CapabilityOutcome | None = None
        try:
            parent, child, routing = await self._media_changes(
                source, transcript, initiator_id=initiator_id
            )
        except Exception:
            logger.exception("Не удалось расшифровать запись %s", source.id)
            error = "Не удалось расшифровать запись"
            parent = {"status": SourceStatus.FAILED, "error": error}
            child = {"status": SourceStatus.FAILED, "error": error}
        async with self._repos.atomic() as repos:
            await repos.projects.lock(source.project_id)
            await repos.sources.patch(source.id, parent, only_status=SourceStatus.PROCESSING)
            # Расшифровку нельзя удалить, пока она `processing` (см. `delete`); удалённая вместе
            # с записью не оживает: patch не найдёт строку.
            await repos.sources.patch(transcript.id, child, only_status=SourceStatus.PROCESSING)
        if routing is not None:
            await self._report_incident(source, routing)
            return
        if parent.get("status") is not SourceStatus.READY:
            return
        if self._derivations is not None and frame_profile(media_profile) is not None:
            # Кадры и vision — после готовой расшифровки: сбой кадров не отменяет звук.
            fresh = await self._repos.sources.get(source.id)
            fresh_transcript = await self._repos.sources.get(transcript.id)
            if fresh is not None and fresh_transcript is not None:
                try:
                    await self._derivations.derive_media(
                        fresh,
                        fresh_transcript,
                        profile_name=media_profile,
                        initiator_id=initiator_id,
                    )
                except Exception:
                    logger.exception("Не удалось построить производные видео для %s", source.id)
                    fresh = await self._repos.sources.get(source.id)
                    if fresh is not None and self._derivations is not None:
                        await self._derivations.append_warning(
                            fresh.id, "Не удалось обработать видеоряд записи"
                        )

    async def _parse_changes(self, *, file_name: str, data: bytes) -> dict[str, Any]:
        """Результат разбора как набор полей источника: `status`, `content`, `error`, `warning`."""
        try:
            parsed = await self._parser.parse_document(file_name=file_name, data=data)
        except DocumentParseError as error:
            return {"status": SourceStatus.FAILED, "error": str(error)}
        text = parsed.text
        if len(text) > self._max_text:
            return {
                "status": SourceStatus.FAILED,
                "error": (
                    f"После разбора файл превышает лимит {self._max_text} символов. "
                    "Разделите файл на части и загрузите их отдельно"
                ),
            }
        return {
            "status": SourceStatus.READY,
            "content": text,
            "error": None,
            "warning": parsed.warning,
            "unreadable_pages": list(parsed.unreadable_pages),
        }

    async def process_file(
        self,
        source_id: UUID,
        *,
        initiator_id: UUID | None = None,
        media_profile: str | None = None,
    ) -> None:
        """Фоновый разбор документа; `initiator_id` — чьи ключи использовать для записи.

        Ключи инициатора загрузки передаются аргументом, а не хранятся в источнике: после
        рестарта сервера `processing`-источники завершаются сбоем (ADR-0012), поэтому
        переживать рестарт ключам не нужно.

        Разбор запускается asyncio-задачей. Результат пишется точечным UPDATE только по
        полям разбора и только пока источник в `processing`: название и `active`, которые
        пользователь поменял за время разбора, не затираются, а удалённый источник не оживает.

        `media_profile` — профиль обработки записи (RFC-0006): от него зависит, извлекаются ли
        кадры и как часто. Для PDF со сканами после разбора запускается OCR производным узлом.
        """
        if self._parse_delay:
            await asyncio.sleep(self._parse_delay)
        source = await self._repos.sources.get(source_id)
        if source is None or source.status is not SourceStatus.PROCESSING or not source.file_key:
            return
        if is_media(source.file_name or ""):
            await self._process_media(
                source, initiator_id=initiator_id, media_profile=media_profile
            )
            return
        try:
            data = await self._storage.load(source.file_key)
            changes = await self._parse_changes(file_name=source.file_name or "", data=data)
        except Exception:
            logger.exception("Не удалось разобрать источник %s", source_id)
            changes = {"status": SourceStatus.FAILED, "error": "Не удалось разобрать файл"}
        # Blob IO и parser закончены: lock охватывает только фиксацию метаданных.
        async with self._repos.atomic() as repos:
            await repos.projects.lock(source.project_id)
            await repos.sources.patch(source_id, changes, only_status=SourceStatus.PROCESSING)
        if changes.get("status") is SourceStatus.READY and changes.get("unreadable_pages"):
            await self._ocr_scans(source_id, initiator_id=initiator_id)

    async def _ocr_scans(self, source_id: UUID, *, initiator_id: UUID | None) -> None:
        """OCR страниц-сканов PDF (RFC-0006, шаг 4): производный узел, не трогая текст разбора.

        Если модели с чтением PDF нет, `prepare_ocr` создаёт неблокирующий технический вопрос
        и возвращает `None`; источник остаётся `ready` с `warning` и `unreadable_pages`.
        """
        if self._derivations is None:
            return
        source = await self._repos.sources.get(source_id)
        if source is None or source.status is not SourceStatus.READY:
            return
        node = await self._derivations.prepare_ocr(source, initiator_id=initiator_id)
        if node is None:
            return
        await self.process_ocr(source.id, node.id, initiator_id=initiator_id)

    async def process_ocr(
        self, source_id: UUID, node_id: UUID, *, initiator_id: UUID | None
    ) -> None:
        """Фоновая OCR-обработка узла; сбой помечает узел, а не теряет источник."""
        if self._derivations is None:
            return
        try:
            await self._derivations.run_ocr(source_id, node_id, initiator_id=initiator_id)
        except Exception:
            logger.exception("Не удалось распознать сканы источника %s", source_id)
            await self._derivations.patch_node_failed(
                node_id, "Не удалось распознать страницы-сканы"
            )

    async def media_file(self, source_id: UUID) -> MediaFileInfo:
        """Размер, MIME, ETag и Last-Modified медиафайла: сам файл отдаёт `read_media`.

        Только аудио и видео: документы этим маршрутом не отдаются (иначе PDF обходил бы
        собственные проверки загрузки).
        """
        source = await self.get(source_id)
        if not is_media(source.file_name or "") or not source.file_key:
            raise NotFoundError("Медиафайл не найден")
        size = source.size_bytes or 0
        if size <= 0:
            raise NotFoundError("Медиафайл не найден")
        digest = hashlib.sha256(f"{source.file_key}:{size}".encode()).hexdigest()[:16]
        mime = source.mime if (source.mime or "").startswith(("audio/", "video/")) else None
        return MediaFileInfo(
            size=size,
            mime=mime or _mime_for(source.file_name or ""),
            etag=f'"{digest}"',
            last_modified=source.created_at,
        )

    async def read_media(self, source_id: UUID, *, start: int, length: int) -> AsyncIterator[bytes]:
        """Поток байт файла из хранилища: плеер не держит запись в памяти целиком.

        `local_file` даёт путь (для in-memory хранилища — временную копию), чтение идёт в
        потоке кусками по 1 МБ; контекст живёт всё время отдачи ответа.
        """
        source = await self.get(source_id)
        if not source.file_key:
            raise NotFoundError("Медиафайл не найден")
        async with self._storage.local_file(source.file_key) as path:
            handle = await asyncio.to_thread(path.open, "rb")
            try:
                await asyncio.to_thread(handle.seek, max(start, 0))
                remaining = max(length, 0)
                while remaining > 0:
                    chunk = await asyncio.to_thread(handle.read, min(_MEDIA_CHUNK, remaining))
                    if not chunk:
                        return
                    remaining -= len(chunk)
                    yield chunk
            finally:
                await asyncio.to_thread(handle.close)

    async def media_segments(
        self, source_id: UUID
    ) -> tuple[Source, Sequence[tuple[float, float, str]]]:
        """Расшифровка и отрезки с таймкодами для перемотки плеера к цитате.

        Если запрос по записи — берётся производная расшифровка; если по самой расшифровке —
        её текст. Длительность для последнего отрезка — у записи или расшифровки.
        """
        source = await self.get(source_id)
        siblings = await self._repos.sources.list_by_project(source.project_id)
        if source.derivation is not None and source.derivation.capability == SPEECH_TO_TEXT:
            transcript = source
        else:
            transcript = next(
                (
                    item
                    for item in siblings
                    if item.parent_id == source.id
                    and item.derivation is not None
                    and item.derivation.capability == SPEECH_TO_TEXT
                ),
                None,
            )
        if transcript is None:
            raise ConflictError("У этого источника нет расшифровки с таймкодами")
        duration = transcript.duration_sec or source.duration_sec
        return transcript, transcript_segments(transcript.content, duration)

    async def retry_ocr(self, source_id: UUID, *, initiator_id: UUID | None) -> Source:
        """Повтор OCR сканов PDF после настройки ключа или разового решения аналитика.

        `«Повторить»` технического вопроса возвращает `derived`-узел, если модель нашлась, и
        `503`, если возможности по-прежнему нет (вопрос при этом уже создан приёмником).
        """
        if self._derivations is None:
            raise UnavailableError("Обработка сканов не включена на сервере")
        source = await self.get(source_id)
        if not (source.file_name or "").lower().endswith(".pdf"):
            raise InvalidInputError("OCR сканов доступен только для PDF")
        if not source.unreadable_pages:
            raise ConflictError("Все страницы уже распознаны: повторять OCR нечего")
        if source.status is SourceStatus.PROCESSING:
            raise ConflictError("Файл ещё разбирается — повторите после окончания разбора")
        if self._derivations is None:  # pragma: no cover - защита от гонки типов
            raise UnavailableError("Обработка сканов не включена на сервере")
        siblings = await self._repos.sources.list_by_project(source.project_id)
        existing = next(
            (
                item
                for item in siblings
                if item.parent_id == source.id
                and item.derivation is not None
                and item.derivation.capability == OCR_CAPABILITY
            ),
            None,
        )
        if existing is not None and existing.status is SourceStatus.PROCESSING:
            raise ConflictError("OCR уже выполняется: дождитесь окончания")
        if existing is not None and existing.edited_by_human:
            raise ConflictError("Текст OCR правил человек: повтор перезапишет правку")
        if existing is None:
            node = await self._derivations.prepare_ocr(source, initiator_id=initiator_id)
            if node is None:
                raise ToolUnavailableError(
                    "Модель с чтением PDF не подключена. Добавьте ключ модели в настройках "
                    "и повторите",
                    reason="capability_missing",
                    remaining=f"страницы {', '.join(map(str, source.unreadable_pages[:30]))}",
                )
            return node
        now = self._rt.clock()
        derivation = existing.derivation
        pages: list[int] = []
        if derivation is not None:
            raw_pages = derivation.params.get("pages")
            if isinstance(raw_pages, list):
                pages = [
                    int(page)
                    for page in raw_pages
                    if isinstance(page, (int, float)) and not isinstance(page, bool)
                ]
            derivation = SourceDerivation(
                capability=derivation.capability,
                provider=derivation.provider,
                model=derivation.model,
                params={**derivation.params, "pages": sorted({*pages, *source.unreadable_pages})},
                cost_usd=derivation.cost_usd,
                created_at=derivation.created_at,
            )
        expected = existing.status
        async with self._repos.atomic() as repos:
            await repos.projects.lock(source.project_id)
            await repos.sources.patch(
                existing.id,
                {"status": SourceStatus.PROCESSING, "error": None, "derivation": derivation},
                only_status=expected,
            )
            await touch_project(repos, source.project_id, now)
        updated = await self._repos.sources.get(existing.id)
        if updated is None or updated.status is not SourceStatus.PROCESSING:
            raise ConflictError("Источник только что изменился — обновите страницу и повторите")
        return updated

    def _content_changes(
        self, source: Source, content: str, *, has_children: bool
    ) -> dict[str, Any]:
        if source.status is SourceStatus.PROCESSING:
            raise InvalidInputError("Файл ещё обрабатывается — текст можно поправить позже")
        if has_children and not source.content:
            raise InvalidInputError("У записи нет своего текста — поправьте производный источник")
        changes: dict[str, Any] = {"content": self._clean_content(content)}
        if source.status is SourceStatus.FAILED:
            changes["status"] = SourceStatus.READY  # аналитик вписал текст вручную
            changes["error"] = None
        if source.origin is SourceOrigin.DERIVED and changes["content"] != source.content:
            # Ревизий пока нет (#34): правка человека перезаписывает текст ИИ с отметкой.
            changes["edited_by_human"] = True
        return changes

    async def update(
        self,
        source_id: UUID,
        *,
        title: str | None,
        content: str | None,
        active: bool | None,
        fields: set[str],
    ) -> Source:
        source = await get_source(self._repos, source_id)
        expected_status = source.status
        async with self._repos.atomic() as repos:
            await repos.projects.lock(source.project_id)
            source = await get_source(repos, source_id)
            if "content" in fields and source.status is not expected_status:
                raise ConflictError("Источник только что изменился — обновите страницу и повторите")
            family = descendants(await repos.sources.list_by_project(source.project_id), source_id)
            changes: dict[str, Any] = {}
            if "title" in fields and title is not None:
                changes["title"] = self._clean_title(title) or source.title
            if "content" in fields and content is not None:
                changes.update(self._content_changes(source, content, has_children=bool(family)))
            if "active" in fields and active is not None:
                changes["active"] = active
            if changes:
                # Правка текста не должна обгонять разбор: статус проверяется в самом UPDATE.
                guard = source.status if "content" in changes else None
                if not await repos.sources.patch(source_id, changes, only_status=guard):
                    await get_source(repos, source_id)  # удалён → 404
                    raise ConflictError(
                        "Источник только что изменился — обновите страницу и повторите"
                    )
            if "active" in changes:
                # Выключенная запись выключает и свои производные, включённая — включает.
                for child in family:
                    await repos.sources.patch(child.id, {"active": changes["active"]})
            if changes.get("status") is SourceStatus.READY and source.parent_id is not None:
                # Аналитик вписал текст вместо неудавшейся расшифровки: запись больше не в сбое.
                await repos.sources.patch(
                    source.parent_id,
                    {"status": SourceStatus.READY, "error": None},
                    only_status=SourceStatus.FAILED,
                )
            source = await get_source(repos, source_id)
            now = self._rt.clock()
            if source.question_id and "content" in fields:
                question = await repos.questions.get(source.question_id)
                if (
                    question is not None
                    and question.answer
                    and question.answer.source_id == source.id
                ):
                    question_rules.update_answer_text(question, text=source.content, now=now)
                    await repos.questions.update(question)
            await touch_project(repos, source.project_id, now)
            return source

    async def delete(self, source_id: UUID) -> None:
        source = await get_source(self._repos, source_id)
        async with self._repos.atomic() as repos:
            await repos.projects.lock(source.project_id)
            source = await get_source(repos, source_id)
            if source.parent_id is not None and source.status is SourceStatus.PROCESSING:
                # Распознавание уже идёт и оплачивается: результат был бы выброшен.
                raise ConflictError(
                    "Запись ещё обрабатывается. Дождитесь окончания или удалите запись целиком"
                )
            now = self._rt.clock()
            # Удаление родителя удаляет производные (FK ON DELETE CASCADE и in-memory так же).
            family = [
                source,
                *descendants(await repos.sources.list_by_project(source.project_id), source_id),
            ]
            for item in family:
                if not item.question_id:
                    continue
                question = await repos.questions.get(item.question_id)
                if (
                    question is not None
                    and question.answer
                    and question.answer.source_id == item.id
                ):
                    question_rules.drop_answer(question, now=now)
                    await repos.questions.update(question)
            await repos.sources.delete(source_id)
            await touch_project(repos, source.project_id, now)
        for item in family:
            if item.file_key:
                await self._storage.delete(item.file_key)
            for frame_key in derivation_frame_keys(item):
                await self._storage.delete(frame_key)


def _mime_for(file_name: str) -> str:
    """Content-Type записи по расширению: браузер не всегда присылает MIME при загрузке."""
    suffix = "." + file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    return _MEDIA_MIME_BY_SUFFIX.get(suffix, "application/octet-stream")
