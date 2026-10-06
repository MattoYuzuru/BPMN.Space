"""Сборщик контекста прогона (RFC §5.2): что видит модель за один прогон.

В контекст идут активные разобранные источники (с id для цитат), вопросы с ответами
и допущениями и текущая схема, если аналитик её правил.

Бюджет: суммарный объём текста источников ограничен (`llm_context_budget_chars`), каждый
источник — не больше `MAX_SOURCE_TEXT_CHARS`. Если всё не помещается, бюджет делится поровну
с перераспределением остатка (короткие источники остаются целыми), а самые старые источники
сверх лимита по числу пропускаются. Всё обрезанное попадает в `RunContext.warnings`.
TODO(real): #6 вместо обрезки — дайджест больших документов, который строится один раз и
кэшируется в `Source.digest` со ссылками на цитаты; ProcessGraph ручной правки — текстом
с пометкой «правки аналитика приоритетнее» (RFC §5.2).
"""

import hashlib
import json
from collections.abc import Sequence
from copy import deepcopy
from typing import Any

from app.domain.analysis import MAX_SOURCE_TEXT_CHARS, ContextSource, RunContext
from app.domain.models import (
    Project,
    Question,
    Source,
    SourceStatus,
    Version,
    VersionOrigin,
)

# Меньше этого источнику не выделяем: короткий обрывок вреднее, чем его отсутствие.
MIN_SOURCE_SHARE_CHARS = 2_000
_WORD_BREAK_WINDOW = 200
_LISTED_TITLES = 3


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def source_snapshot_hash(sources: Sequence[Source]) -> str:
    """Снимок всех источников, включая inactive/processing; текст в аудит не копируется."""
    values = sorted(
        [
            (
                str(s.id),
                s.kind.value,
                s.title,
                s.status.value,
                s.active,
                _digest(s.content),
                str(s.question_id),
                s.created_at.isoformat(),
            )
            for s in sources
        ]
    )
    return _digest(json.dumps(values, ensure_ascii=False))


def _cut(text: str, limit: int) -> str:
    """Обрезает по границе слова, если она рядом, чтобы не рвать слово посередине."""
    if len(text) <= limit:
        return text
    head = text[:limit]
    space = head.rfind(" ", max(limit - _WORD_BREAK_WINDOW, 0))
    return head[:space] if space > 0 else head


def _allocate(lengths: list[int], budget: int) -> list[int]:
    """Делит `budget` между источниками: короткие остаются целыми, остаток — длинным."""
    allocation = list(lengths)
    remaining = budget
    order = sorted(range(len(lengths)), key=lengths.__getitem__)
    for position, index in enumerate(order):
        share = remaining // (len(order) - position)
        allocation[index] = min(lengths[index], share)
        remaining -= allocation[index]
    return allocation


def _titles(sources: Sequence[ContextSource]) -> str:
    titles = ", ".join(f"«{s.title[:60]}»" for s in sources[:_LISTED_TITLES])
    rest = len(sources) - _LISTED_TITLES
    return f"{titles} и ещё {rest}" if rest > 0 else titles


def fit_sources(
    sources: list[ContextSource], *, budget_chars: int
) -> tuple[list[ContextSource], list[str]]:
    """Источники, вмещающиеся в бюджет, и предупреждения о том, что пришлось урезать."""
    warnings: list[str] = []
    budget = max(budget_chars, MIN_SOURCE_SHARE_CHARS)
    keep_count = max(budget // MIN_SOURCE_SHARE_CHARS, 1)
    kept = sources
    if len(sources) > keep_count:
        # Источники идут по возрастанию `created_at`: пропускаем самые старые.
        dropped = sources[: len(sources) - keep_count]
        kept = sources[len(dropped) :]
        warnings.append(
            f"В контекст модели не поместились {len(dropped)} самых старых источников "
            f"({_titles(dropped)}) — они в этом прогоне не учтены"
        )
    capped = [min(len(s.content), MAX_SOURCE_TEXT_CHARS) for s in kept]
    allocation = _allocate(capped, budget) if sum(capped) > budget else capped
    fitted: list[ContextSource] = []
    trimmed: list[ContextSource] = []
    for source, limit in zip(kept, allocation, strict=True):
        if limit < len(source.content):
            trimmed.append(source)
            source = ContextSource(  # noqa: PLW2901 — подменяем обрезанной копией
                id=source.id,
                kind=source.kind,
                title=source.title,
                content=_cut(source.content, limit),
                created_at=source.created_at,
            )
        fitted.append(source)
    if trimmed:
        warnings.append(
            f"Из-за лимита контекста модели ({budget} символов на все источники) обрезаны "
            f"{len(trimmed)} из {len(kept)}: {_titles(trimmed)} — модель видит только начало текста"
        )
    return fitted, warnings


def build_run_context(
    *,
    project: Project,
    sources: Sequence[Source],
    questions: Sequence[Question],
    versions: Sequence[Version],
    budget_chars: int = 120_000,
) -> RunContext:
    latest = versions[0] if versions else None
    usable = [
        ContextSource(
            id=s.id, kind=s.kind, title=s.title, content=s.content, created_at=s.created_at
        )
        for s in sources
        if s.active and s.status is SourceStatus.READY and s.content.strip()
    ]
    fitted, warnings = fit_sources(usable, budget_chars=budget_chars)
    unavailable = [s for s in sources if s.active and s.status is not SourceStatus.READY]
    if unavailable:
        warnings.append(
            f"Активных источников без готового текста: {len(unavailable)}. Их содержимое ещё не "
            "учтено; исключение вопросов как неактуальных не подтверждается неполным контекстом."
        )
    return RunContext(
        project_id=project.id,
        project_title=project.title,
        sources=fitted,
        questions=deepcopy(list(questions)),
        current_xml=latest.xml if latest else None,
        current_trace=dict(latest.trace) if latest else {},
        base_version_id=latest.id if latest else None,
        base_generated_xml=next(
            (
                v.xml
                for v in versions
                if v.origin is VersionOrigin.GENERATED
                and latest is not None
                and v.number < latest.number
            ),
            None,
        ),
        current_is_manual=latest is not None and latest.origin is VersionOrigin.MANUAL,
        generated_versions=sum(1 for v in versions if v.origin is VersionOrigin.GENERATED),
        warnings=warnings,
        evidence_sources=usable,
        analysis_budget_chars=budget_chars,
        source_snapshot_hash=source_snapshot_hash(sources),
        analysis_input_complete=not unavailable,
    )


def describe_context(context: RunContext) -> dict[str, Any]:
    """Компактный след контекста для аудита вызова модели (`llm_calls.request`).

    Тексты источников и XML не копируются в каждый вызов: остаются id, длина и SHA-256,
    по которым видно, какая именно версия текста была у модели. Сами тексты лежат в `sources`.
    """
    return {
        "project_id": str(context.project_id),
        "project_title": context.project_title,
        "sources": [
            {
                "id": str(s.id),
                "title": s.title,
                "kind": s.kind.value,
                "chars": len(s.content),
                "sha256": _digest(s.content),
            }
            for s in context.sources
        ],
        "questions": [{"code": q.code, "status": q.status.value} for q in context.questions],
        "current_xml": (
            {"chars": len(context.current_xml), "sha256": _digest(context.current_xml)}
            if context.current_xml
            else None
        ),
        "current_is_manual": context.current_is_manual,
        "analysis_sources": [
            {
                "id": str(s.id),
                "kind": s.kind.value,
                "chars": len(s.content),
                "sha256": _digest(s.content),
            }
            for s in (
                context.evidence_sources
                if context.evidence_sources is not None
                else context.sources
            )
        ],
        "analysis_budget_chars": context.analysis_budget_chars,
        "source_snapshot_hash": context.source_snapshot_hash,
        "analysis_input_complete": context.analysis_input_complete,
        "generated_versions": context.generated_versions,
        "warnings": context.warnings,
    }
