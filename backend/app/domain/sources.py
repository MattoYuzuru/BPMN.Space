"""Правила дерева материалов (RFC-0006): сериализация происхождения и обход потомков."""

from collections.abc import Iterable
from datetime import datetime
from typing import Any
from uuid import UUID

from app.domain.models import MediaInfo, Source, SourceDerivation

# Возможность «речь → текст» (RFC-0006): расшифровка записи — производный источник.
SPEECH_TO_TEXT = "speech_to_text"
TRANSCRIPT_TITLE = "Расшифровка"


def derivation_to_json(value: SourceDerivation | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "capability": value.capability,
        "provider": value.provider,
        "model": value.model,
        "params": dict(value.params),
        "cost_usd": value.cost_usd,
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
