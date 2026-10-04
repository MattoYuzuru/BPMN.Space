"""Учебные материалы («Примеры»): список и добавление в проект как обычного источника.

Оркестрация здесь, а не в `ingest`/`infra`: это независимые слои. Документ идёт тем же путём,
что загрузка файла (`SourceService.create_file`: копия в хранилище и разбор), голосовая
заметка — как проверенная расшифровка (`create_text(kind=voice)`).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.domain.models import Source, SourceKind
from app.fixtures import read_text
from app.fixtures.samples import Sample, SampleKind, read_sample_file, sample_size
from app.services.errors import NotFoundError
from app.services.sources import SourceService


@dataclass(frozen=True, slots=True, kw_only=True)
class SampleView:
    id: str
    title: str
    kind: SampleKind
    format: str
    size_bytes: int
    tour: bool


class SampleService:
    def __init__(self, sources: SourceService, *, samples: Sequence[Sample]) -> None:
        self._sources = sources
        self._samples = {sample.id: sample for sample in samples}

    def list(self) -> list[SampleView]:
        return [
            SampleView(
                id=sample.id,
                title=sample.title,
                kind=sample.kind,
                format=sample.format,
                size_bytes=sample_size(sample),
                tour=sample.tour,
            )
            for sample in self._samples.values()
        ]

    async def add(self, project_id: UUID, sample_id: str) -> tuple[Source, bool]:
        """Добавляет материал источником. Второе значение — «дочитать в фоне» (`process_file`)."""
        sample = self._samples.get(sample_id)
        if sample is None:
            raise NotFoundError("Учебный материал не найден")
        if sample.kind is SampleKind.VOICE:
            source = await self._sources.create_text(
                project_id,
                content=read_text(sample.transcript or ""),
                title=sample.title,
                kind=SourceKind.VOICE,
                duration_sec=None,
            )
            return source, False
        return await self._sources.create_file(
            project_id,
            file_name=sample.title,
            mime=sample.mime,
            data=read_sample_file(sample.file or ""),
            title=None,
        )
