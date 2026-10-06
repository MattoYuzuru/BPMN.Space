"""IR → BPMN 2.0 без DI. Раскладка и полноценный линт — отдельный runtime-порт."""

from xml.etree.ElementTree import Element, SubElement, indent, register_namespace, tostring

from app.domain.bpmn.document import BPMN_NS
from app.domain.bpmn.ir import FlowIR, GraphIR, NodeIR, validate_graph

XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
register_namespace("bpmn", BPMN_NS)
register_namespace("xsi", XSI_NS)
TAGS = {
    "start": "startEvent",
    "end": "endEvent",
    "task": "task",
    "xor": "exclusiveGateway",
    "and": "parallelGateway",
}


def _q(tag: str) -> str:
    return f"{{{BPMN_NS}}}{tag}"


def compile_graph(graph: GraphIR) -> str:
    validate_graph(graph)
    root = Element(
        _q("definitions"),
        {
            "id": "Definitions_IR",
            "targetNamespace": "https://bpmn.space/ir/1",
            "exporter": "Архитектор BPMN",
        },
    )
    collaboration = SubElement(root, _q("collaboration"), {"id": graph.collaboration_id})
    SubElement(
        collaboration,
        _q("participant"),
        {"id": graph.participant_id, "name": graph.title, "processRef": graph.process_id},
    )
    for node in graph.nodes:
        if node.type == "start" and node.event_kind == "message":
            SubElement(
                root,
                _q("message"),
                {
                    "id": node.message_id or f"Message_{node.id}",
                    "name": node.message_name or node.name,
                },
            )
    process = SubElement(root, _q("process"), {"id": graph.process_id, "isExecutable": "false"})
    if graph.process_name:
        process.set("name", graph.process_name)
    lane_set = SubElement(process, _q("laneSet"), {"id": "LaneSet_IR"})
    for lane in graph.lanes:
        element = SubElement(lane_set, _q("lane"), {"id": lane.id, "name": lane.name})
        for node in sorted(graph.nodes, key=lambda n: n.id):
            if node.lane == lane.id:
                SubElement(element, _q("flowNodeRef")).text = node.id
    for node in sorted(graph.nodes, key=lambda n: n.id):
        _emit_node(process, node, graph.flows)
    for flow in sorted(graph.flows, key=lambda f: f.id):
        _emit_flow(process, flow)
    indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(root, encoding="unicode") + "\n"


def _emit_node(process: Element, node: NodeIR, flows: list[FlowIR]) -> None:
    attrs = {"id": node.id, "name": node.name}
    if node.type in {"xor", "and"}:
        attrs["gatewayDirection"] = "Diverging" if node.direction == "split" else "Converging"
    default = next((f.id for f in flows if f.source_id == node.id and f.default), None)
    if default:
        attrs["default"] = default
    element = SubElement(
        process, _q(node.task_kind if node.type == "task" else TAGS[node.type]), attrs
    )
    for flow in sorted(flows, key=lambda f: f.id):
        if flow.target_id == node.id:
            SubElement(element, _q("incoming")).text = flow.id
    for flow in sorted(flows, key=lambda f: f.id):
        if flow.source_id == node.id:
            SubElement(element, _q("outgoing")).text = flow.id
    if node.type == "start" and node.event_kind == "message":
        SubElement(
            element,
            _q("messageEventDefinition"),
            {"messageRef": node.message_id or f"Message_{node.id}"},
        )


def _emit_flow(process: Element, flow: FlowIR) -> None:
    attrs = {"id": flow.id, "sourceRef": flow.source_id, "targetRef": flow.target_id}
    if flow.name:
        attrs["name"] = flow.name
    element = SubElement(process, _q("sequenceFlow"), attrs)
    if flow.condition:
        SubElement(
            element, _q("conditionExpression"), {f"{{{XSI_NS}}}type": "bpmn:tFormalExpression"}
        ).text = flow.condition
