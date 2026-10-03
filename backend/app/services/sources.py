"""Сценарии источников: текст и расшифровка голоса, загрузка файла, правка, выключение, удаление."""

import asyncio
import logging
from uuid import UUID

from app.domain import questions as question_rules
from app.domain.models import Source, SourceKind, SourceStatus
from app.domain.projects import default_source_title
from app.infra.repositories.base import Repositories
from app.infra.storage import FileStorage
from app.ingest.parsers import (
    DocumentParseError,
    DocumentParser,
    UnsupportedFormatError,
    detect_format,
    is_slow,
)
from app.services.common import Runtime, get_project, get_source, touch_project
from app.services.errors import (
    InvalidInputError,
    PayloadTooLargeError,
    UnsupportedMediaError,
)

logger = logging.getLogger(__name__)

MAX_SOURCE_TITLE = 200


def _format_duration(seconds: float) -> str:
    total = round(seconds)
    return f"{total // 60}:{total % 60:02d}"


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
    ) -> None:
        self._repos = repos
        self._parser = parser
        self._storage = storage
        self._rt = runtime
        self._max_text = max_text_chars
        self._max_upload = max_upload_bytes
        self._parse_delay = parse_delay_sec

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

    async def create_text(
        self,
        project_id: UUID,
        *,
        content: str,
        title: str | None,
        kind: SourceKind,
        duration_sec: float | None,
    ) -> Source:
        """Текст или проверенная аналитиком расшифровка голосовой заметки (`kind=voice`)."""
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
        )
        await self._repos.sources.add(source)
        await touch_project(self._repos, project_id, now)
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
        """Сохраняет файл. Возвращает источник и флаг «дочитать в фоне» (`process_file`).

        `.txt`/`.md` разбираются сразу (`ready`), `.docx`/`.pdf` — в фоне (`processing`).
        """
        await get_project(self._repos, project_id)
        try:
            fmt = detect_format(file_name)
        except UnsupportedFormatError as error:
            raise UnsupportedMediaError(str(error)) from error
        if not data:
            raise InvalidInputError("Файл пустой")
        if len(data) > self._max_upload:
            limit_mb = self._max_upload // (1024 * 1024)
            raise PayloadTooLargeError(f"Файл больше {limit_mb} МБ")

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
            await self._parse_into(source, data)
        await self._repos.sources.add(source)
        await touch_project(self._repos, project_id, now)
        return source, background

    async def _parse_into(self, source: Source, data: bytes) -> None:
        try:
            text = await self._parser.parse(file_name=source.file_name or "", data=data)
        except DocumentParseError as error:
            source.status = SourceStatus.FAILED
            source.error = str(error)
            return
        if len(text) > self._max_text:
            text = text[: self._max_text]
        source.content = text
        source.status = SourceStatus.READY
        source.error = None

    async def process_file(self, source_id: UUID) -> None:
        """Фоновый разбор документа.

        Разбор запускается asyncio-задачей; статус источника сохраняется в БД.
        """
        await asyncio.sleep(self._parse_delay)
        source = await self._repos.sources.get(source_id)
        if source is None or source.status is not SourceStatus.PROCESSING or not source.file_key:
            return
        try:
            data = await self._storage.load(source.file_key)
            await self._parse_into(source, data)
        except Exception:
            logger.exception("Не удалось разобрать источник %s", source_id)
            source.status = SourceStatus.FAILED
            source.error = "Не удалось разобрать файл"
        await self._repos.sources.update(source)

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
        if "title" in fields and title is not None:
            source.title = self._clean_title(title) or source.title
        if "content" in fields and content is not None:
            if source.status is SourceStatus.PROCESSING:
                raise InvalidInputError("Файл ещё обрабатывается — текст можно поправить позже")
            source.content = self._clean_content(content)
            if source.status is SourceStatus.FAILED:
                source.status = SourceStatus.READY  # аналитик вписал текст вручную
                source.error = None
        if "active" in fields and active is not None:
            source.active = active
        await self._repos.sources.update(source)
        now = self._rt.clock()
        if source.question_id and "content" in fields:
            question = await self._repos.questions.get(source.question_id)
            if question is not None and question.answer and question.answer.source_id == source.id:
                question_rules.update_answer_text(question, text=source.content, now=now)
                await self._repos.questions.update(question)
        await touch_project(self._repos, source.project_id, now)
        return source

    async def delete(self, source_id: UUID) -> None:
        source = await get_source(self._repos, source_id)
        now = self._rt.clock()
        if source.question_id:
            question = await self._repos.questions.get(source.question_id)
            if question is not None and question.answer and question.answer.source_id == source.id:
                question_rules.drop_answer(question, now=now)
                await self._repos.questions.update(question)
        if source.file_key:
            await self._storage.delete(source.file_key)
        await self._repos.sources.delete(source_id)
        await touch_project(self._repos, source.project_id, now)
