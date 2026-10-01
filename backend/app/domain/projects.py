"""Правила уровня проекта: статус выводится из состояния, а не хранится (нечему разъезжаться)."""

from app.domain.models import ProjectStatus, RunMode


def derive_status(
    *, has_sources: bool, open_questions: int, active_run_mode: RunMode | None
) -> ProjectStatus:
    """Статус для списка проектов и шапки.

    Идёт прогон → `analyzing`/`building`; нет активных источников → `empty`;
    есть открытые вопросы → `needs_answers`; иначе → `ready` (можно строить или схема готова).
    """
    if active_run_mode is RunMode.ANALYZE:
        return ProjectStatus.ANALYZING
    if active_run_mode is RunMode.BUILD:
        return ProjectStatus.BUILDING
    if not has_sources:
        return ProjectStatus.EMPTY
    if open_questions > 0:
        return ProjectStatus.NEEDS_ANSWERS
    return ProjectStatus.READY


def default_source_title(content: str, *, limit: int = 60) -> str:
    """Название источника по умолчанию — первая непустая строка текста (без `#` заголовка)."""
    first = next((line for line in content.splitlines() if line.strip()), "")
    words = " ".join(first.split()).lstrip("#").strip()
    if len(words) <= limit:
        return words
    cut = words[:limit].rsplit(" ", 1)[0]
    return f"{cut}…"
