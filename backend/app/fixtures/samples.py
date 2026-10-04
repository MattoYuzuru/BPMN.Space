"""Учебные материалы («Примеры»): документы и голосовая заметка для первых шагов в продукте.

Документы лежат в `samples/` и собираются командой `make fixtures` (`scripts/build_fixtures.py`):
`.docx` тура — из текстов `texts/`, остальные — копии текстов. Голосовая заметка — только
расшифровка: она добавляется сразу как источник `kind=voice`, без аудио и распознавания.
Реестр — только данные и чтение файлов (без импортов из слоёв приложения).
"""

from dataclasses import dataclass
from enum import StrEnum
from functools import cache

from app.fixtures import SAMPLES_DIR, read_text


class SampleKind(StrEnum):
    DOCUMENT = "document"
    VOICE = "voice"


@dataclass(frozen=True, slots=True)
class Sample:
    id: str
    title: str  # для документа — имя файла с расширением, как оно попадёт в источник
    kind: SampleKind
    format: str  # docx, md, txt или voice
    mime: str | None = None
    file: str | None = None  # имя файла в samples/ (латиницей); у голоса нет
    transcript: str | None = None  # имя текста в texts/ для голосовой заметки
    tour: bool = False  # документ тура: на нём модель стабильно задаёт вопросы


TOUR_SAMPLE_ID = "tp861-meeting-note"

SAMPLES: tuple[Sample, ...] = (
    Sample(
        id=TOUR_SAMPLE_ID,
        title="Записка со встречи — техприсоединение.docx",
        kind=SampleKind.DOCUMENT,
        format="docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file="tp861-meeting-note.docx",
        tour=True,
    ),
    Sample(
        id="repair-outage",
        title="Регламент вывода оборудования в ремонт.md",
        kind=SampleKind.DOCUMENT,
        format="md",
        mime="text/markdown",
        file="repair-outage.md",
    ),
    Sample(
        id="work-permit",
        title="Работы по наряду-допуску.txt",
        kind=SampleKind.DOCUMENT,
        format="txt",
        mime="text/plain",
        file="work-permit.txt",
    ),
    Sample(
        id="voice-request-approval",
        title="Голосовая заметка — согласование заявки",
        kind=SampleKind.VOICE,
        format="voice",
        transcript="sample_voice_note.txt",
    ),
)

# Текст для шага тура «Опишите процесс»: подсказка-автодополнение в поле текста.
TOUR_TEXT_SUGGESTION_FILE = "tour_text_suggestion.txt"


def tour_text_suggestion() -> str:
    return read_text(TOUR_TEXT_SUGGESTION_FILE)


@cache
def read_sample_file(name: str) -> bytes:
    return (SAMPLES_DIR / name).read_bytes()


def sample_size(sample: Sample) -> int:
    """Размер в байтах: файл целиком или текст расшифровки в UTF-8."""
    if sample.file:
        return len(read_sample_file(sample.file))
    return len(read_text(sample.transcript or "").encode("utf-8"))
