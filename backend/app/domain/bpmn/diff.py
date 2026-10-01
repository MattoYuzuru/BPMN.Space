"""Дифф двух версий схемы по узлам и дорожкам (RFC §2.4: «добавлено 2 задачи, удалена 1»).

TODO(real): #5 дифф на уровне ProcessGraph (RFC §5.6 `diff.py`): учитывать потоки и условия,
сопоставлять узлы без общих id (переименование vs удаление + добавление).
"""

from app.domain.bpmn.document import BpmnDocument
from app.domain.models import VersionDiff


def diff_documents(old: BpmnDocument | None, new: BpmnDocument) -> VersionDiff:
    """Сравнивает элементы по id: новые, удалённые и изменённые (имя, тип или дорожка)."""
    if old is None:
        return VersionDiff(added=len(new.element_ids))

    old_items = _signatures(old)
    new_items = _signatures(new)
    added = new_items.keys() - old_items.keys()
    removed = old_items.keys() - new_items.keys()
    changed = [
        key for key in new_items.keys() & old_items.keys() if new_items[key] != old_items[key]
    ]
    return VersionDiff(added=len(added), removed=len(removed), changed=len(changed))


def _signatures(document: BpmnDocument) -> dict[str, tuple[str, str, str | None]]:
    items: dict[str, tuple[str, str, str | None]] = {
        node.id: (node.type, node.name, node.lane_id) for node in document.nodes.values()
    }
    for lane in document.lanes:
        items[lane.id] = ("lane", lane.name, None)
    return items
