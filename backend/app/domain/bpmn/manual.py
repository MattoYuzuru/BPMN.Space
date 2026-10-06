"""Защищённые ручные изменения относительно generated-базы; без произвольного XML от модели."""

from dataclasses import dataclass, field
from typing import Any

from app.domain.bpmn.ir import GraphIR

_FIELDS = ("nodes", "flows", "lanes")


def semantic_value(item: Any) -> dict[str, Any]:
    return item.model_dump(mode="json", exclude={"source", "assumption_of"})


@dataclass(slots=True)
class ManualPolicy:
    protected: dict[str, set[str]] = field(default_factory=lambda: {key: set() for key in _FIELDS})
    root_fields: set[str] = field(default_factory=set[str])
    removed: dict[str, set[str]] = field(default_factory=lambda: {key: set() for key in _FIELDS})

    @classmethod
    def compare(
        cls, current: GraphIR, base: GraphIR | None, inherited: dict[str, Any] | None = None
    ) -> "ManualPolicy":
        policy = cls(
            root_fields={
                name
                for name in ("title", "process_name")
                if base is None or getattr(current, name) != getattr(base, name)
            }
        )
        if inherited:
            policy.root_fields.update(inherited.get("root_fields", []))
        for field_name in _FIELDS:
            before = {x.id: x for x in getattr(base, field_name)} if base else {}
            after = {x.id: x for x in getattr(current, field_name)}
            policy.protected[field_name] = {
                key
                for key, item in after.items()
                if key not in before or semantic_value(item) != semantic_value(before[key])
            }
            policy.removed[field_name] = set(before) - set(after)
            if inherited:
                policy.protected[field_name].update(
                    inherited.get("protected", {}).get(field_name, [])
                )
                policy.removed[field_name].update(inherited.get("removed", {}).get(field_name, []))
            policy.protected[field_name].intersection_update(after)
            policy.removed[field_name].difference_update(after)
        return policy

    @classmethod
    def restore(cls, value: dict[str, Any]) -> "ManualPolicy":
        return cls(
            root_fields=set(value.get("root_fields", [])),
            protected={key: set(value.get("protected", {}).get(key, [])) for key in _FIELDS},
            removed={key: set(value.get("removed", {}).get(key, [])) for key in _FIELDS},
        )

    def dump(self) -> dict[str, Any]:
        return {
            "root_fields": sorted(self.root_fields),
            "protected": {key: sorted(value) for key, value in self.protected.items()},
            "removed": {key: sorted(value) for key, value in self.removed.items()},
        }

    def merge(self, candidate: GraphIR, current: GraphIR) -> tuple[GraphIR, list[dict[str, Any]]]:
        """Manual имеет приоритет. Несогласованные соединения после merge ловит validator/repair."""
        updates: dict[str, Any] = {}
        conflicts: list[dict[str, Any]] = []
        for field_name in _FIELDS:
            old = {x.id: x for x in getattr(current, field_name)}
            proposed = {
                x.id: x
                for x in getattr(candidate, field_name)
                if x.id not in self.removed[field_name]
            }
            for key in self.protected[field_name]:
                if key not in old:
                    continue
                change = proposed.get(key)
                if change is not None and semantic_value(old[key]) != semantic_value(change):
                    conflicts.append(
                        {
                            "element_id": key,
                            "manual": semantic_value(old[key]),
                            "proposed": semantic_value(change),
                            "source": change.source.model_dump(mode="json")
                            if change.source
                            else None,
                        }
                    )
                proposed[key] = old[key]
            if field_name == "flows":
                # Новый id не позволяет обойти protected routing у вручную добавленного шлюза.
                protected_controls = {
                    node.id
                    for node in current.nodes
                    if node.id in self.protected["nodes"]
                    and node.type in {"xor", "and", "start", "end"}
                }
                owned = {flow.id for flow in current.flows if flow.source_id in protected_controls}
                proposed = {
                    key: flow
                    for key, flow in proposed.items()
                    if flow.source_id not in protected_controls or key in owned
                }
                for flow in current.flows:
                    if flow.id in owned:
                        proposed[flow.id] = flow
            updates[field_name] = list(proposed.values())
        # У защищённой стрелки могут быть неизменённые опорные узлы, которые модель опустила.
        nodes = {x.id: x for x in updates["nodes"]}
        old_nodes = {x.id: x for x in current.nodes}
        for flow in updates["flows"]:
            for key in (flow.source_id, flow.target_id):
                if key not in nodes and key in old_nodes and key not in self.removed["nodes"]:
                    nodes[key] = old_nodes[key]
        updates["nodes"] = list(nodes.values())
        lanes = {x.id: x for x in updates["lanes"]}
        old_lanes = {x.id: x for x in current.lanes}
        for node in nodes.values():
            if node.lane not in lanes and node.lane in old_lanes:
                lanes[node.lane] = old_lanes[node.lane]
        used = {node.lane for node in nodes.values()}
        lane_order = {lane.id: index for index, lane in enumerate(current.lanes)}
        updates["lanes"] = sorted(
            (x for x in lanes.values() if x.id in used),
            key=lambda lane: lane_order.get(lane.id, 1000),
        )
        updates.update({key: getattr(current, key) for key in self.root_fields})
        updates.update(
            process_name=current.process_name,
            process_id=current.process_id,
            participant_id=current.participant_id,
            collaboration_id=current.collaboration_id,
        )
        return candidate.model_copy(update=updates), conflicts
