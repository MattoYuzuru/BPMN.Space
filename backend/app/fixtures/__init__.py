"""Демо-данные mock-бэкенда (#2): тексты источников, BPMN-схемы и записанные «ответы модели».

Только данные, без логики и без I/O, кроме чтения собственных файлов. Читают их:
- сиды in-memory тестового хранилища и Postgres — `app/infra/seed.py`;
- mock-пайплайн LLM — `app/llm/mock.py` (правила `playbook.py`);
- каталог примеров — `examples.py`.

Схемы в `bpmn/` пересобирает `backend/scripts/build_fixtures.py` (раскладка bpmn-auto-layout,
проверки XSD и bpmnlint). Как добавить фикстуру — `docs/backend/mock.md`.
Postgres заполняется идемпотентным демо-сидом при старте; `playbook.py` остаётся записанной
моделью для mock-режима и тестов (RFC §9.1).
"""

from functools import cache
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent
TEXTS_DIR = FIXTURES_DIR / "texts"
BPMN_DIR = FIXTURES_DIR / "bpmn"
SAMPLES_DIR = FIXTURES_DIR / "samples"


@cache
def read_text(name: str) -> str:
    """Текст источника из `texts/` (UTF-8, без завершающего перевода строки)."""
    return (TEXTS_DIR / name).read_text(encoding="utf-8").strip()


@cache
def read_bpmn(name: str) -> str:
    """Готовая схема из `bpmn/<name>.bpmn` (с координатами)."""
    return (BPMN_DIR / f"{name}.bpmn").read_text(encoding="utf-8")


def bpmn_names() -> list[str]:
    return sorted(path.stem for path in BPMN_DIR.glob("*.bpmn"))
