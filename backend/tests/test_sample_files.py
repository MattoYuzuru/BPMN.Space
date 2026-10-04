"""Закоммиченные учебные материалы не отстают от текстов в `texts/` (забытый `make fixtures`)."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from app.fixtures import SAMPLES_DIR, read_text
from app.fixtures.samples import SAMPLES, read_sample_file
from app.ingest.parsers import LocalDocumentParser

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_fixtures.py"


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_fixtures", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _parser() -> LocalDocumentParser:
    return LocalDocumentParser(
        max_text_chars=40_000, max_pdf_chars=200_000, max_pdf_pages=10, timeout_sec=10
    )


async def test_tour_docx_text_matches_source_texts() -> None:
    expected = "\n".join(
        [
            "Записка со встречи — техприсоединение",
            read_text("tp861_meeting_note.txt"),
            read_text("tour_note_addendum.txt"),
        ]
    )
    sample = next(item for item in SAMPLES if item.tour)
    assert sample.file is not None
    parsed = await _parser().parse(file_name=sample.title, data=read_sample_file(sample.file))
    assert parsed == expected


@pytest.mark.parametrize(
    ("file", "source"),
    [("repair-outage.md", "repair_outage.md"), ("work-permit.txt", "work_permit.md")],
)
async def test_text_samples_match_source_texts(file: str, source: str) -> None:
    parsed = await _parser().parse(file_name=file, data=read_sample_file(file))
    assert parsed.strip() == read_text(source)


def test_committed_files_equal_regenerated_ones() -> None:
    """Файлы пересобираются детерминированно: расхождение значит, что забыли `make fixtures`."""
    for name, content in _script().sample_files().items():
        assert (SAMPLES_DIR / name).read_bytes() == content, f"{name} устарел: make fixtures"
