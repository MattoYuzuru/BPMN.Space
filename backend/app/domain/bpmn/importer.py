"""BPMN → проверяемый граф. Неподдерживаемая семантика не превращается в линейный процесс."""

from collections import defaultdict, deque
from typing import Literal, cast
from xml.etree.ElementTree import Element, tostring

from defusedxml.ElementTree import fromstring

from app.domain.bpmn.document import BPMN_NS, BPMNDI_NS, ensure_safe_xml
from app.domain.bpmn.ir import FlowIR, GraphIR, GraphValidationError, LaneIR, NodeIR
from app.domain.models import Quote

TYPES: dict[str, Literal["start", "end", "task", "xor", "and"]] = {
    "startEvent": "start",
    "endEvent": "end",
    "task": "task",
    "userTask": "task",
    "manualTask": "task",
    "sendTask": "task",
    "receiveTask": "task",
    "serviceTask": "task",
    "exclusiveGateway": "xor",
    "parallelGateway": "and",
}


def _q(tag: str) -> str:
    return f"{{{BPMN_NS}}}{tag}"


def _attrs(element: Element, allowed: set[str]) -> None:
    if set(element.attrib) - allowed:
        raise GraphValidationError(
            [f"manual: {element.get('id', element.tag)} содержит атрибуты вне IR"]
        )


def _process(root: Element) -> Element:
    processes = root.findall(_q("process"))
    if len(processes) != 1:
        raise GraphValidationError(["manual: поддержан один process/pool; текущий XML сохранён"])
    for doc in root.iter(_q("documentation")):
        if (doc.text or "").strip() or doc.attrib or list(doc):
            raise GraphValidationError(
                ["manual: документация — opaque данные вне IR; текущий XML сохранён"]
            )
    process = processes[0]
    _attrs(process, {"id", "name", "isExecutable"})
    if process.get("isExecutable", "false") != "false":
        raise GraphValidationError(["manual: executable-процесс вне поддерживаемого IR"])
    allowed = {_q("process"), _q("collaboration"), _q("message"), f"{{{BPMNDI_NS}}}BPMNDiagram"}
    if any(element.tag not in allowed for element in root):
        raise GraphValidationError(["manual: определения ресурсов/событий вне текущего IR"])
    return process


def _flows(process: Element) -> list[FlowIR]:
    result: list[FlowIR] = []
    for element in process.findall(_q("sequenceFlow")):
        _attrs(element, {"id", "name", "sourceRef", "targetRef"})
        if any(child.tag != _q("conditionExpression") for child in element):
            raise GraphValidationError(
                [f"manual: {element.get('id')} содержит opaque свойства потока"]
            )
        expression = element.find(_q("conditionExpression"))
        if expression is not None and (
            set(expression.attrib) - {"{http://www.w3.org/2001/XMLSchema-instance}type"}
            or list(expression)
        ):
            raise GraphValidationError(
                [f"manual: {element.get('id')} имеет язык/свойства условия вне IR"]
            )
        result.append(
            FlowIR(
                id=element.attrib["id"],
                source_id=element.get("sourceRef", ""),
                target_id=element.get("targetRef", ""),
                name=element.get("name", ""),
                condition=element.findtext(_q("conditionExpression")) or None,
                default=any(node.get("default") == element.get("id") for node in process),
            )
        )
    return result


def _lanes(process: Element) -> tuple[list[LaneIR], dict[str, str]]:
    lanes: list[LaneIR] = []
    lane_of: dict[str, str] = {}
    for element in process.iter(_q("lane")):
        _attrs(element, {"id", "name"})
        if any(child.tag != _q("flowNodeRef") for child in element):
            raise GraphValidationError(
                [f"manual: {element.get('id')} имеет вложенные/opaque свойства дорожки"]
            )
        lane_id = element.attrib["id"]
        lanes.append(LaneIR(id=lane_id, name=element.get("name") or lane_id))
        for ref in element.findall(_q("flowNodeRef")):
            lane_of[(ref.text or "").strip()] = lane_id
    return lanes, lane_of


def _event(
    element: Element, root: Element
) -> tuple[Literal["none", "message"], str | None, str | None]:
    definitions = [child for child in element if child.tag.endswith("EventDefinition")]
    if not definitions:
        return "none", None, None
    if (
        element.tag != _q("startEvent")
        or len(definitions) != 1
        or definitions[0].tag != _q("messageEventDefinition")
    ):
        raise GraphValidationError([f"manual: {element.get('id')} содержит тип события вне IR"])
    definition = definitions[0]
    _attrs(definition, {"id", "messageRef"})
    if list(definition):
        raise GraphValidationError(["manual: свойства message event вне IR"])
    message_id = definition.get("messageRef")
    message = next((m for m in root.findall(_q("message")) if m.get("id") == message_id), None)
    if message is None:
        raise GraphValidationError(["manual: messageRef не найден"])
    _attrs(message, {"id", "name"})
    if list(message):
        raise GraphValidationError(["manual: свойства message вне IR"])
    return "message", message_id, message.get("name") or message_id


def _node(
    element: Element,
    root: Element,
    *,
    lane_of: dict[str, str],
    ins: dict[str, int],
    outs: dict[str, int],
) -> NodeIR:
    tag = element.tag.removeprefix(f"{{{BPMN_NS}}}")
    if tag not in TYPES:
        raise GraphValidationError(
            [f"manual: неподдерживаемый элемент {element.get('id', tag)} ({tag})"]
        )
    _attrs(
        element,
        {"id", "name", "gatewayDirection", "default"}
        if tag.endswith("Gateway")
        else {"id", "name"},
    )
    allowed = {_q("incoming"), _q("outgoing"), _q("messageEventDefinition")}
    if any(child.tag not in allowed for child in element):
        raise GraphValidationError([f"manual: {element.get('id')} имеет свойства вне IR"])
    event_kind, message_id, message_name = _event(element, root)
    node_id = element.attrib["id"]
    direction: Literal["split", "join"] | None = None
    if tag.endswith("Gateway"):
        if ins[node_id] > 1 and outs[node_id] > 1:
            raise GraphValidationError([f"manual: {node_id} совмещает join/fork"])
        direction = "split" if outs[node_id] > 1 else "join"
        declared = element.get("gatewayDirection", "Unspecified")
        expected = "Diverging" if direction == "split" else "Converging"
        if declared not in {"Unspecified", expected}:
            raise GraphValidationError([f"manual: {node_id} имеет несовместимый gatewayDirection"])
    return NodeIR(
        id=node_id,
        type=TYPES[tag],
        task_kind=cast(
            Literal["task", "userTask", "manualTask", "sendTask", "receiveTask", "serviceTask"],
            tag if TYPES[tag] == "task" else "task",
        ),
        name=element.get("name")
        or {"startEvent": "Начало", "endEvent": "Завершение", "parallelGateway": "Параллельно"}.get(
            tag, node_id
        ),
        lane=lane_of.get(node_id, "Lane_Unassigned"),
        direction=direction,
        event_kind=event_kind,
        message_id=message_id,
        message_name=message_name,
    )


def _join_pairs(nodes: list[NodeIR], edges: dict[str, set[str]]) -> list[NodeIR]:
    result = list(nodes)
    for index, node in enumerate(nodes):
        if node.type != "and" or node.direction != "split":
            continue
        distances: list[dict[str, int]] = []
        for target in edges[node.id]:
            distance = {target: 0}
            queue = deque([target])
            while queue:
                current = queue.popleft()
                for neighbor in edges[current]:
                    if neighbor not in distance and neighbor != node.id:
                        distance[neighbor] = distance[current] + 1
                        queue.append(neighbor)
            distances.append(distance)
        candidates = [
            candidate
            for candidate in nodes
            if candidate.type == "and"
            and candidate.direction == "join"
            and all(candidate.id in distance for distance in distances)
        ]
        if candidates:
            chosen = min(candidates, key=lambda candidate: sum(d[candidate.id] for d in distances))
            result[index] = node.model_copy(update={"join_id": chosen.id})
    return result


def _participants(root: Element) -> tuple[Element | None, str]:
    collaborations = root.findall(_q("collaboration"))
    participants = [p for c in collaborations for p in c.findall(_q("participant"))]
    if len(collaborations) > 1 or len(participants) > 1:
        raise GraphValidationError(["manual: несколько участников/коллабораций вне IR"])
    for collaboration in collaborations:
        _attrs(collaboration, {"id", "name"})
        if any(child.tag != _q("participant") for child in collaboration):
            raise GraphValidationError(["manual: message flow/свойства коллаборации вне IR"])
    if participants:
        _attrs(participants[0], {"id", "name", "processRef"})
        if list(participants[0]):
            raise GraphValidationError(["manual: multiplicity/свойства участника вне IR"])
    return participants[0] if participants else None, collaborations[0].get(
        "id", "Collaboration_1"
    ) if collaborations else "Collaboration_1"


def import_graph(xml: str) -> GraphIR:
    ensure_safe_xml(xml)
    root = fromstring(xml.encode())
    process = _process(root)
    flows = _flows(process)
    ins: dict[str, int] = defaultdict(int)
    outs: dict[str, int] = defaultdict(int)
    edges: dict[str, set[str]] = defaultdict(set)
    for flow in flows:
        ins[flow.target_id] += 1
        outs[flow.source_id] += 1
        edges[flow.source_id].add(flow.target_id)
    lanes, lane_of = _lanes(process)
    nodes = [
        _node(element, root, lane_of=lane_of, ins=ins, outs=outs)
        for element in process
        if element.tag not in {_q("laneSet"), _q("sequenceFlow")}
    ]
    if any(node.lane == "Lane_Unassigned" for node in nodes):
        lanes.append(LaneIR(id="Lane_Unassigned", name="Исполнитель"))
    used = {node.lane for node in nodes}
    lanes = [lane for lane in lanes if lane.id in used]
    participant, collaboration_id = _participants(root)
    return GraphIR(
        title=participant.get("name") or "Процесс" if participant is not None else "Процесс",
        process_name=process.get("name"),
        process_id=process.attrib["id"],
        participant_id=participant.get("id", "Participant_1")
        if participant is not None
        else "Participant_1",
        collaboration_id=collaboration_id,
        lanes=lanes,
        nodes=_join_pairs(nodes, edges),
        flows=flows,
    )


def _semantic_tree(element: Element) -> object:
    children = [
        _semantic_tree(child)
        for child in element
        if child.tag not in {_q("incoming"), _q("outgoing")}
    ]
    if element.tag == _q("lane"):
        children.sort(key=repr)
    return (
        element.tag,
        tuple(
            sorted(
                (key, " ".join(value.split()) if key == "name" else value)
                for key, value in element.attrib.items()
            )
        ),
        (element.text or "").strip(),
        tuple(children),
    )


def semantic_signatures(xml: str) -> dict[str, str]:
    """DI/indentation/attr order не меняют provenance; смысловые поля и документация меняют."""
    root = fromstring(xml.encode())
    role_of = {
        ref.text: (lane.get("id"), lane.get("name"))
        for lane in root.iter(_q("lane"))
        for ref in lane.findall(_q("flowNodeRef"))
    }
    return {
        element.attrib["id"]: repr((role_of.get(element.attrib["id"]), _semantic_tree(element)))
        for process in root.findall(_q("process"))
        for element in process.iter()
        if element.get("id")
    }


def retain_trace(previous_xml: str, current_xml: str, trace: dict[str, Quote]) -> dict[str, Quote]:
    before, after = semantic_signatures(previous_xml), semantic_signatures(current_xml)
    return {
        key: quote for key, quote in trace.items() if key in after and before.get(key) == after[key]
    }


def _box(bounds: Element) -> tuple[float, float, float, float]:
    return (
        float(bounds.get("x", "0")),
        float(bounds.get("y", "0")),
        float(bounds.get("width", "0")),
        float(bounds.get("height", "0")),
    )


def _geometry_keys(graph: GraphIR) -> dict[str, object]:
    result: dict[str, object] = {}
    for node in graph.nodes:
        value = node.model_dump(exclude={"source", "assumption_of"})
        if node.event_kind == "message":
            value.update(
                message_id=node.message_id or f"Message_{node.id}",
                message_name=node.message_name or node.name,
            )
        result[node.id] = value
    for flow in graph.flows:
        result[flow.id] = flow.model_dump(exclude={"source", "assumption_of"})
    for lane in graph.lanes:
        # При добавлении задачи membership меняется, геометрия старой дорожки остаётся опорой.
        result[lane.id] = lane.name
    result[graph.participant_id] = ("participant", graph.process_id)
    return result


def _di_map(root: Element, kind: str) -> dict[str, Element]:
    return {e.get("bpmnElement", ""): e for e in root.iter(f"{{{BPMNDI_NS}}}{kind}")}


DC_BOUNDS = "{http://www.omg.org/spec/DD/20100524/DC}Bounds"
DI_POINT = "{http://www.omg.org/spec/DD/20100524/DI}waypoint"


def _restore_shapes(
    new: dict[str, Element], old: dict[str, Element], stable: set[str]
) -> dict[str, tuple[float, float, float, float]]:
    fixed: dict[str, tuple[float, float, float, float]] = {}
    for key in stable & new.keys() & old.keys():
        before, after = old[key].find(DC_BOUNDS), new[key].find(DC_BOUNDS)
        if before is None or after is None:
            continue
        after.attrib.clear()
        after.attrib.update(before.attrib)
        # Цвета и прочие DI-атрибуты остаются пользовательскими; id даёт новый layouter.
        new[key].attrib.update({k: v for k, v in old[key].attrib.items() if k != "id"})
        for child in old[key]:
            if child.tag != DC_BOUNDS:
                for existing in list(new[key]):
                    if existing.tag == child.tag:
                        new[key].remove(existing)
                new[key].append(fromstring(tostring(child)))
        fixed[key] = _box(after)
    return fixed


def _position_new(
    shapes: dict[str, Element],
    fixed: dict[str, tuple[float, float, float, float]],
    node_ids: set[str],
) -> None:
    occupied = [box for key, box in fixed.items() if key in node_ids]
    for key in sorted(node_ids - fixed.keys()):
        bounds = shapes[key].find(DC_BOUNDS)
        if bounds is None:
            continue
        x, y, width, height = _box(bounds)
        for _ in range(200):
            overlaps = [
                b
                for b in occupied
                if x < b[0] + b[2] + 24
                and x + width + 24 > b[0]
                and y < b[1] + b[3] + 24
                and y + height + 24 > b[1]
            ]
            if not overlaps:
                break
            x = max(b[0] + b[2] + 100 for b in overlaps)
        bounds.set("x", str(x))
        occupied.append((x, y, width, height))


def _expand_container(container: Element, children: list[Element]) -> None:
    bounds = container.find(DC_BOUNDS)
    boxes = [child.find(DC_BOUNDS) for child in children]
    rectangles = [_box(box) for box in boxes if box is not None]
    if bounds is None or not rectangles:
        return
    x, y, width, height = _box(bounds)
    right = max([x + width, *(b[0] + b[2] + 48 for b in rectangles)])
    bottom = max([y + height, *(b[1] + b[3] + 36 for b in rectangles)])
    x = min([x, *(b[0] - 36 for b in rectangles)])
    y = min([y, *(b[1] - 24 for b in rectangles)])
    bounds.attrib.update(x=str(x), y=str(y), width=str(right - x), height=str(bottom - y))


def _resize_lanes(shapes: dict[str, Element], graph: GraphIR) -> None:
    # Неизменённые узлы никогда не сдвигаем. Новые узлы их дорожки размещаем по старому y.
    for lane in graph.lanes:
        container = shapes.get(lane.id)
        if container is None:
            continue
        nodes = [shapes[n.id] for n in graph.nodes if n.lane == lane.id and n.id in shapes]
        _expand_container(container, nodes)
    participant = shapes.get(graph.participant_id)
    if participant is not None:
        _expand_container(
            participant, [shapes[lane.id] for lane in graph.lanes if lane.id in shapes]
        )


def _restore_edges(
    new: dict[str, Element],
    old: dict[str, Element],
    shapes: dict[str, Element],
    *,
    graph: GraphIR,
    stable: set[str],
    fixed: set[str],
) -> None:
    for flow in graph.flows:
        edge = new.get(flow.id)
        if edge is None:
            continue
        if flow.id in stable and flow.id in old and {flow.source_id, flow.target_id} <= fixed:
            for child in list(edge):
                edge.remove(child)
            for child in old[flow.id]:
                edge.append(fromstring(tostring(child)))
            edge.attrib.update({k: v for k, v in old[flow.id].attrib.items() if k != "id"})
            continue
        a, b = shapes[flow.source_id].find(DC_BOUNDS), shapes[flow.target_id].find(DC_BOUNDS)
        if a is None or b is None:
            continue
        ax, ay, aw, ah = _box(a)
        bx, by, _bw, bh = _box(b)
        x1, y1, x2, y2 = ax + aw, ay + ah / 2, bx, by + bh / 2
        for child in list(edge):
            if child.tag == DI_POINT:
                edge.remove(child)
        for x, y in ((x1, y1), ((x1 + x2) / 2, y1), ((x1 + x2) / 2, y2), (x2, y2)):
            edge.append(Element(DI_POINT, {"x": str(x), "y": str(y)}))


def preserve_geometry(layout_xml: str, previous_xml: str) -> str:
    """Ручной DI сохраняется; containers расширяются для новых/сдвинутых фигур."""
    graph, old_graph = import_graph(layout_xml), import_graph(previous_xml)
    before, after = _geometry_keys(old_graph), _geometry_keys(graph)
    if before == after and (graph.title, graph.process_name) == (
        old_graph.title,
        old_graph.process_name,
    ):
        # Это действительно прежняя семантика: сохраняем весь DI, labels и цвета без roundtrip.
        return previous_xml
    new, old = fromstring(layout_xml.encode()), fromstring(previous_xml.encode())
    stable = {key for key in before.keys() & after.keys() if before[key] == after[key]}
    shapes = _di_map(new, "BPMNShape")
    fixed = _restore_shapes(shapes, _di_map(old, "BPMNShape"), stable)
    _position_new(shapes, fixed, {node.id for node in graph.nodes})
    _resize_lanes(shapes, graph)
    _restore_edges(
        _di_map(new, "BPMNEdge"),
        _di_map(old, "BPMNEdge"),
        shapes,
        graph=graph,
        stable=stable,
        fixed=set(fixed),
    )
    return tostring(new, encoding="unicode")
