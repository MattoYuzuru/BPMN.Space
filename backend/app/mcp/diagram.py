"""Чтение схемы для MCP: последняя версия, сводка IR и элементы выбранной дорожки.

Слой представления не ходит в infra: версия приходит из `services.versions`, разбор XML — из
`domain.bpmn` (документ и импортёр IR). Разбор синхронный и выносится в поток, чтобы не держать
событийный цикл на больших схемах.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from app.domain.bpmn.document import BpmnDocument, BpmnLane, parse_bpmn
from app.domain.models import Version
from app.services.errors import InvalidInputError, NotFoundError
from app.services.projects import ProjectDetail

__all__ = [
    "LaneSelection",
    "lane_selection",
    "latest_version",
    "parse_document",
    "project_ir_summary",
]


@dataclass(frozen=True, slots=True)
class LaneSelection:
    """Найденная дорожка: имя, id и элементы схемы, которые в неё входят."""

    name: str
    lane_id: str
    element_ids: frozenset[str]

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "lane_id": self.lane_id,
            "element_ids": sorted(self.element_ids),
            "elements_count": len(self.element_ids),
        }


async def latest_version(container: Any, project_id: Any) -> Version:
    """Последняя версия схемы проекта или понятная ошибка, если схемы ещё нет."""
    page, _ = await container.versions.list_page(project_id, limit=1)
    if not page:
        raise NotFoundError("Схема ещё не собрана: сначала запустите сборку (start_run)")
    return await container.versions.get(page[0].id)


def parse_document(xml: str) -> BpmnDocument:
    """Разобрать XML в плоскую модель (может бросить `BpmnFormatError`)."""
    return parse_bpmn(xml)


async def parse_document_async(xml: str) -> BpmnDocument:
    return await asyncio.to_thread(parse_document, xml)


def _find_lane(document: BpmnDocument, lane: str) -> BpmnLane:
    needle = " ".join(lane.split()).casefold()
    matches = [item for item in document.lanes if item.name.casefold() == needle]
    if not matches:
        known = ", ".join(f"«{item.name}»" for item in document.lanes) or "дорожек нет"
        raise InvalidInputError(f"Дорожка «{lane}» не найдена. Доступные дорожки: {known}")
    return matches[0]


def lane_selection(document: BpmnDocument, lane: str) -> LaneSelection:
    """Элементы дорожки: её собственный id и узлы, привязанные к ней в BPMN DI."""
    found = _find_lane(document, lane)
    return LaneSelection(
        name=found.name,
        lane_id=found.id,
        element_ids=frozenset(
            {found.id, *(node.id for node in document.nodes.values() if node.lane_id == found.id)}
        ),
    )


def project_ir_summary(
    document: BpmnDocument, detail: ProjectDetail | None = None
) -> dict[str, Any]:
    """Компактная сводка схемы: участники, дорожки, число узлов и потоков, раскладка.

    Дополнительно (если передан `ProjectDetail`) — счётчики и статус проекта: агенту нужен
    контекст «что уже в проекте», не полный REST-ответ.
    """
    summary: dict[str, Any] = {
        "participants": list(document.participants),
        "lanes": [lane.name for lane in document.lanes],
        "nodes": len(document.nodes),
        "flows": len(document.flows),
        "has_layout": document.has_layout,
    }
    if detail is not None:
        summary["sources"] = len(detail.sources)
        summary["questions_open"] = detail.summary.open + detail.summary.new
        summary["questions_resolved"] = detail.summary.resolved
    return summary
