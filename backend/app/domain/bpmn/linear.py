"""Компилятор линейного процесса в BPMN 2.0 с координатами (DI).

Сборщик линейного процесса: старт → шаги по дорожкам → конец, без шлюзов. Его используют сид
демо-данных и mock-пайплайн. Рабочий LLM-пайплайн использует `ir.py` и `compiler.py`.
Результат проходит XSD и bpmnlint (`bpmnlint:recommended`) — это проверяют тесты.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from xml.etree.ElementTree import Element, SubElement, indent, register_namespace, tostring

from app.domain.bpmn.document import BPMN_NS, BPMNDI_NS, DC_NS, DI_NS

_POOL_X = 160
_POOL_Y = 80
_POOL_HEADER = 30
_LANE_HEIGHT = 140
_COLUMN = 170
_TASK_W, _TASK_H = 110, 80
_EVENT = 36
_LEFT_PAD = 60

register_namespace("bpmn", BPMN_NS)
register_namespace("bpmndi", BPMNDI_NS)
register_namespace("dc", DC_NS)
register_namespace("di", DI_NS)


@dataclass(frozen=True, slots=True)
class LinearStep:
    name: str
    lane: str


@dataclass(frozen=True, slots=True)
class _Box:
    x: float
    y: float
    w: float
    h: float

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


def _q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


@dataclass(frozen=True, slots=True)
class _Node:
    id: str
    tag: str
    name: str
    lane: str


def build_linear_diagram(
    *,
    process_name: str,
    steps: Sequence[LinearStep],
    start_name: str = "Процесс начат",
    end_name: str = "Процесс завершён",
    key: str = "Linear",
) -> str:
    """Собирает схему. Id задач — `Task_1…N` по порядку шагов, дорожек — `Lane_1…K`."""
    if not steps:
        raise ValueError("Нужен хотя бы один шаг процесса")

    lanes = list(dict.fromkeys(step.lane for step in steps))
    nodes = [_Node(id="StartEvent_1", tag="startEvent", name=start_name, lane=steps[0].lane)]
    nodes += [
        _Node(id=f"Task_{i}", tag="task", name=step.name, lane=step.lane)
        for i, step in enumerate(steps, start=1)
    ]
    nodes.append(_Node(id="EndEvent_1", tag="endEvent", name=end_name, lane=steps[-1].lane))
    flows = [(f"Flow_{i}", nodes[i - 1].id, nodes[i].id) for i in range(1, len(nodes))]

    root = Element(
        _q(BPMN_NS, "definitions"),
        {
            "id": f"Definitions_{key}",
            "targetNamespace": "http://arkhitektor.local/bpmn",
            "exporter": "Архитектор BPMN-диаграмм",
            "exporterVersion": "0.1.0",
        },
    )
    collaboration = SubElement(root, _q(BPMN_NS, "collaboration"), {"id": f"Collaboration_{key}"})
    SubElement(
        collaboration,
        _q(BPMN_NS, "participant"),
        {"id": f"Participant_{key}", "name": process_name, "processRef": f"Process_{key}"},
    )
    _semantic(root, key, lanes, nodes, flows)
    _diagram(root, key, lanes, nodes, flows)
    indent(root, space="  ")
    body = tostring(root, encoding="unicode")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{body}\n'


def _lane_id(lanes: Sequence[str], name: str) -> str:
    return f"Lane_{lanes.index(name) + 1}"


def _semantic(
    root: Element,
    key: str,
    lanes: Sequence[str],
    nodes: Sequence[_Node],
    flows: Sequence[tuple[str, str, str]],
) -> None:
    process = SubElement(
        root, _q(BPMN_NS, "process"), {"id": f"Process_{key}", "isExecutable": "false"}
    )
    lane_set = SubElement(process, _q(BPMN_NS, "laneSet"), {"id": f"LaneSet_{key}"})
    for name in lanes:
        lane = SubElement(
            lane_set, _q(BPMN_NS, "lane"), {"id": _lane_id(lanes, name), "name": name}
        )
        for node in (n for n in nodes if n.lane == name):
            SubElement(lane, _q(BPMN_NS, "flowNodeRef")).text = node.id

    for index, node in enumerate(nodes):
        element = SubElement(process, _q(BPMN_NS, node.tag), {"id": node.id, "name": node.name})
        if index > 0:
            SubElement(element, _q(BPMN_NS, "incoming")).text = flows[index - 1][0]
        if index < len(flows):
            SubElement(element, _q(BPMN_NS, "outgoing")).text = flows[index][0]
    for flow_id, source, target in flows:
        attrs = {"id": flow_id, "sourceRef": source, "targetRef": target}
        SubElement(process, _q(BPMN_NS, "sequenceFlow"), attrs)


def _diagram(
    root: Element,
    key: str,
    lanes: Sequence[str],
    nodes: Sequence[_Node],
    flows: Sequence[tuple[str, str, str]],
) -> None:
    boxes = _layout(nodes, lanes)
    width = _POOL_HEADER + _LEFT_PAD + len(nodes) * _COLUMN
    diagram = SubElement(root, _q(BPMNDI_NS, "BPMNDiagram"), {"id": f"Diagram_{key}"})
    plane = SubElement(
        diagram,
        _q(BPMNDI_NS, "BPMNPlane"),
        {"id": f"Plane_{key}", "bpmnElement": f"Collaboration_{key}"},
    )
    _shape(plane, f"Participant_{key}", _Box(_POOL_X, _POOL_Y, width, _LANE_HEIGHT * len(lanes)))
    for i, name in enumerate(lanes):
        lane_y = _POOL_Y + i * _LANE_HEIGHT
        lane_box = _Box(_POOL_X + _POOL_HEADER, lane_y, width - _POOL_HEADER, _LANE_HEIGHT)
        _shape(plane, _lane_id(lanes, name), lane_box)
    for node in nodes:
        box = boxes[node.id]
        shape = _shape(plane, node.id, box, horizontal=False)
        if node.tag.endswith("Event"):
            label = SubElement(shape, _q(BPMNDI_NS, "BPMNLabel"))
            _bounds(label, _Box(box.x - 32, box.y + box.h + 6, 100, 28))
    for flow_id, source, target in flows:
        edge = SubElement(
            plane, _q(BPMNDI_NS, "BPMNEdge"), {"id": f"{flow_id}_di", "bpmnElement": flow_id}
        )
        for x, y in _route(boxes[source], boxes[target]):
            SubElement(edge, _q(DI_NS, "waypoint"), {"x": _num(x), "y": _num(y)})


def _layout(nodes: Sequence[_Node], lanes: Sequence[str]) -> dict[str, _Box]:
    boxes: dict[str, _Box] = {}
    for column, node in enumerate(nodes):
        center_x = _POOL_X + _POOL_HEADER + _LEFT_PAD + column * _COLUMN + _TASK_W / 2
        center_y = _POOL_Y + lanes.index(node.lane) * _LANE_HEIGHT + _LANE_HEIGHT / 2
        w, h = (_EVENT, _EVENT) if node.tag.endswith("Event") else (_TASK_W, _TASK_H)
        boxes[node.id] = _Box(center_x - w / 2, center_y - h / 2, w, h)
    return boxes


def _route(source: _Box, target: _Box) -> list[tuple[float, float]]:
    start = (source.x + source.w, source.cy)
    end = (target.x, target.cy)
    if source.cy == target.cy:
        return [start, end]
    middle = (start[0] + end[0]) / 2
    return [start, (middle, start[1]), (middle, end[1]), end]


def _shape(plane: Element, element_id: str, box: _Box, *, horizontal: bool = True) -> Element:
    attrs = {"id": f"{element_id}_di", "bpmnElement": element_id}
    if horizontal:
        attrs["isHorizontal"] = "true"
    shape = SubElement(plane, _q(BPMNDI_NS, "BPMNShape"), attrs)
    _bounds(shape, box)
    return shape


def _bounds(parent: Element, box: _Box) -> None:
    SubElement(
        parent,
        _q(DC_NS, "Bounds"),
        {"x": _num(box.x), "y": _num(box.y), "width": _num(box.w), "height": _num(box.h)},
    )


def _num(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"
