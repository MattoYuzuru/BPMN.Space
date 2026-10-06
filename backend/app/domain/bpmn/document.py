"""Чтение BPMN 2.0 XML в плоскую модель: участники, дорожки, узлы, потоки.

Модель используется для диффа версий, подписей дорожек и ограниченного mock-линта.
`importer.py` отдельно переводит поддерживаемую семантику XML в GraphIR для повторной
сборки, а неподдерживаемую отвергает без уплощения. XSD-проверка — в `bpmn/xsd.py`.
"""

from dataclasses import dataclass, field
from xml.etree.ElementTree import Element, ParseError, TreeBuilder

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import DefusedXMLParser, fromstring

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMNDI_NS = "http://www.omg.org/spec/BPMN/20100524/DI"
DC_NS = "http://www.omg.org/spec/DD/20100524/DC"
DI_NS = "http://www.omg.org/spec/DD/20100524/DI"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
# Расширения bpmn-js: цвета элементов.
COLOR_NS = "http://www.omg.org/spec/BPMN/non-normative/color/1.0"
BIOCOLOR_NS = "http://bpmn.io/schema/bpmn/biocolor/1.0"
# Пространства имён, допустимые в XML от пользователя (см. `ensure_safe_xml`).
ALLOWED_NAMESPACES = frozenset({BPMN_NS, BPMNDI_NS, DC_NS, DI_NS, XSI_NS, COLOR_NS, BIOCOLOR_NS})

FLOW_NODE_TAGS = frozenset(
    {
        "task",
        "userTask",
        "serviceTask",
        "sendTask",
        "receiveTask",
        "manualTask",
        "scriptTask",
        "businessRuleTask",
        "callActivity",
        "subProcess",
        "startEvent",
        "endEvent",
        "intermediateCatchEvent",
        "intermediateThrowEvent",
        "boundaryEvent",
        "exclusiveGateway",
        "parallelGateway",
        "inclusiveGateway",
        "eventBasedGateway",
        "complexGateway",
    }
)


class BpmnFormatError(ValueError):
    """XML повреждён или не является BPMN 2.0. Сообщение — для пользователя."""


@dataclass(slots=True, kw_only=True)
class BpmnNode:
    id: str
    type: str
    name: str
    lane_id: str | None = None
    incoming: int = 0
    outgoing: int = 0


@dataclass(slots=True, kw_only=True)
class BpmnFlow:
    id: str
    source: str
    target: str
    name: str = ""


@dataclass(slots=True, kw_only=True)
class BpmnLane:
    id: str
    name: str


@dataclass(slots=True, kw_only=True)
class BpmnDocument:
    participants: list[str] = field(default_factory=list[str])
    lanes: list[BpmnLane] = field(default_factory=list[BpmnLane])
    nodes: dict[str, BpmnNode] = field(default_factory=dict[str, BpmnNode])
    flows: list[BpmnFlow] = field(default_factory=list[BpmnFlow])
    shapes: int = 0

    @property
    def element_ids(self) -> set[str]:
        return {*self.nodes, *(lane.id for lane in self.lanes)}

    @property
    def all_element_ids(self) -> set[str]:
        """В том числе стрелки: их условия тоже имеют provenance и assumption bindings."""
        return self.element_ids | {flow.id for flow in self.flows}

    @property
    def has_layout(self) -> bool:
        """Есть ли координаты (DI) — без них bpmn.io покажет пустой холст."""
        return self.shapes > 0


def _tag(element: Element, ns: str = BPMN_NS) -> str | None:
    prefix = f"{{{ns}}}"
    return element.tag[len(prefix) :] if element.tag.startswith(prefix) else None


def _name(element: Element) -> str:
    return " ".join((element.get("name") or "").split())


def parse_bpmn(xml: str) -> BpmnDocument:
    """Разбирает BPMN XML. Небезопасные конструкции (DTD, сущности) запрещены."""
    try:
        root = fromstring(xml.encode("utf-8"))
    except ParseError as error:
        line, column = error.position
        raise BpmnFormatError(f"XML повреждён: строка {line}, столбец {column}") from error
    except DefusedXmlException as error:
        raise BpmnFormatError("XML содержит запрещённые конструкции (DTD или сущности)") from error

    if _tag(root) != "definitions":
        raise BpmnFormatError("Это не BPMN 2.0: корневой элемент должен быть bpmn:definitions")

    processes = [child for child in root if _tag(child) == "process"]
    if not processes:
        raise BpmnFormatError("В схеме нет ни одного процесса (bpmn:process)")

    document = BpmnDocument()
    for collaboration in (c for c in root if _tag(c) == "collaboration"):
        document.participants += [_name(p) for p in collaboration if _tag(p) == "participant"]

    for process in processes:
        _collect_process(process, document)

    for flow in document.flows:
        if flow.source in document.nodes:
            document.nodes[flow.source].outgoing += 1
        if flow.target in document.nodes:
            document.nodes[flow.target].incoming += 1

    document.shapes = sum(1 for _ in root.iter(f"{{{BPMNDI_NS}}}BPMNShape"))
    return document


def _collect_process(process: Element, document: BpmnDocument) -> None:
    lane_of: dict[str, str] = {}
    for lane in process.iter(f"{{{BPMN_NS}}}lane"):
        lane_id = lane.get("id", "")
        document.lanes.append(BpmnLane(id=lane_id, name=_name(lane)))
        for ref in lane.iter(f"{{{BPMN_NS}}}flowNodeRef"):
            lane_of[(ref.text or "").strip()] = lane_id
    for element in process.iter():
        tag = _tag(element)
        element_id = element.get("id")
        if not element_id:
            continue
        if tag in FLOW_NODE_TAGS:
            document.nodes[element_id] = BpmnNode(
                id=element_id, type=tag, name=_name(element), lane_id=lane_of.get(element_id)
            )
        elif tag == "sequenceFlow":
            document.flows.append(
                BpmnFlow(
                    id=element_id,
                    source=element.get("sourceRef", ""),
                    target=element.get("targetRef", ""),
                    name=_name(element),
                )
            )


def _namespace(name: str) -> str | None:
    return name[1:].partition("}")[0] if name.startswith("{") else None


class _NoProcessingInstructions(TreeBuilder):
    """Инструкции обработки (`<?xml-stylesheet …?>`) — вектор XSLT/XSS; в BPMN их быть не должно."""

    def pi(self, target: str, text: str | None = None) -> Element:  # noqa: ARG002
        raise BpmnFormatError("XML содержит инструкции обработки (<?…?>), это запрещено")


def ensure_safe_xml(xml: str) -> None:
    """Проверка XML от пользователя перед сохранением: только BPMN-пространства имён.

    Запрещены DTD и сущности (XXE, «бомба миллиарда смехов»), сетевые и внешние ссылки,
    инструкции обработки, любые элементы и атрибуты вне разрешённых пространств имён.
    Так отсекаются `<script>` из XHTML/SVG (XSS, если файл откроют как документ), а штатный
    `bpmn:script` у `scriptTask` остаётся: браузер его не исполняет. Нарушение — `BpmnFormatError`.
    """
    parser = DefusedXMLParser(
        target=_NoProcessingInstructions(),
        forbid_dtd=True,
        forbid_entities=True,
        forbid_external=True,
    )
    try:
        parser.feed(xml.encode("utf-8"))
        root = parser.close()
    except ParseError as error:
        line, column = error.position
        raise BpmnFormatError(f"XML повреждён: строка {line}, столбец {column}") from error
    except DefusedXmlException as error:
        raise BpmnFormatError("XML содержит запрещённые конструкции (DTD или сущности)") from error

    for element in root.iter():
        namespace = _namespace(element.tag)
        if namespace not in ALLOWED_NAMESPACES:
            raise BpmnFormatError(
                f"Элемент «{element.tag}» вне пространств имён BPMN 2.0 — сохранение запрещено"
            )
        for attribute in element.attrib:
            attribute_namespace = _namespace(attribute)
            if attribute_namespace is not None and attribute_namespace not in ALLOWED_NAMESPACES:
                raise BpmnFormatError(f"Атрибут «{attribute}» вне пространств имён BPMN 2.0")
