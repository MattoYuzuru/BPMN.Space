"""Правила дерева материалов (RFC-0006): сериализация происхождения и обход потомков."""

import re
from collections.abc import Iterable
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from app.domain.models import MediaInfo, Source, SourceDerivation

# Возможность «речь → текст» (RFC-0006): расшифровка записи — производный источник.
SPEECH_TO_TEXT = "speech_to_text"
TRANSCRIPT_TITLE = "Расшифровка"
# Возможности производных узлов волны 3. `frames` и `media_feed` — работа кода (ffmpeg и
# сведение ленты), поэтому провайдер у них не модель; `ocr`, `vision` и `summary` — модель.
OCR = "ocr"
VISION = "vision"
KEY_FRAMES = "frames"
MEDIA_FEED = "media_feed"
SUMMARY = "summary"


def derivation_frame_keys(source: Source) -> list[str]:
    """Ключи файлов кадров из `derivation.params` производного узла (для уборки хранилища).

    Кадры лежат в том же uploads-хранилище, что и записи: при удалении записи и её
    производных их нужно удалить, иначе диск VPS заполнится молча.
    """
    derivation = source.derivation
    if derivation is None:
        return []
    frames = derivation.params.get("frames")
    if not isinstance(frames, list):
        return []
    keys: list[str] = []
    for item in cast("list[object]", frames):
        if not isinstance(item, dict):
            continue
        key = cast("dict[str, object]", item).get("key")
        if isinstance(key, str):
            keys.append(key)
    return keys


def derivation_to_json(value: SourceDerivation | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "capability": value.capability,
        "provider": value.provider,
        "model": value.model,
        "params": dict(value.params),
        "cost_usd": value.cost_usd,
        "credential_id": str(value.credential_id) if value.credential_id else None,
        "created_at": value.created_at.isoformat(),
    }


def derivation_from_json(value: dict[str, Any] | None) -> SourceDerivation | None:
    if not value:
        return None
    return SourceDerivation(
        capability=str(value.get("capability", "")),
        provider=str(value.get("provider", "")),
        model=value.get("model"),
        params=dict(value.get("params") or {}),
        cost_usd=value.get("cost_usd"),
        credential_id=UUID(credential_id)
        if (credential_id := value.get("credential_id"))
        else None,
        created_at=datetime.fromisoformat(value["created_at"]),
    )


def media_to_json(value: MediaInfo | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {"has_audio": value.has_audio, "has_video": value.has_video}


def media_from_json(value: dict[str, Any] | None) -> MediaInfo | None:
    if value is None:
        return None
    return MediaInfo(has_audio=value.get("has_audio"), has_video=value.get("has_video"))


def descendants(sources: Iterable[Source], root_id: UUID) -> list[Source]:
    """Все потомки `root_id` (дети, внуки…) в порядке обхода в ширину; сам корень не входит."""
    children: dict[UUID, list[Source]] = {}
    for source in sources:
        if source.parent_id is not None:
            children.setdefault(source.parent_id, []).append(source)
    found: list[Source] = []
    seen = {root_id}
    queue = [root_id]
    while queue:
        for child in children.get(queue.pop(0), []):
            if child.id not in seen:
                seen.add(child.id)
                found.append(child)
                queue.append(child.id)
    return found


_TIMECODE = re.compile(r"^\[(?P<minutes>\d{1,4}):(?P<seconds>\d{2})\]\s*(?P<body>.+)$")


def transcript_segments(
    content: str, duration_sec: float | None = None
) -> list[tuple[float, float, str]]:
    """Отрезки `[мм:сс] текст` расшифровки: (начало, конец, текст).

    Плеер перематывает к таймкоду цитаты по этим отрезкам; конец — начало следующей реплики
    или длительность записи. Строки без таймкода пропускаются: они не привязаны ко времени.
    """
    starts: list[tuple[float, str]] = []
    for line in content.splitlines():
        match = _TIMECODE.match(line.strip())
        if match is None:
            continue
        at_sec = int(match.group("minutes")) * 60 + int(match.group("seconds"))
        body = match.group("body").strip()
        if body:
            starts.append((float(at_sec), body))
    segments: list[tuple[float, float, str]] = []
    for index, (start, text) in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else None
        if end is None:
            end = (
                duration_sec if duration_sec is not None and duration_sec > start else start + 30.0
            )
        segments.append((start, max(end, start), text))
    return segments
