"""Типизированный граф IR v1: один процесс, явные стрелки, без неявного AND.

Условия — подписи сценариев, не исполняемый код. Неизвестные поля/типы отклоняются;
XML, DI, message flow и opaque элементы модель через этот контракт не передаёт.
"""

from collections import defaultdict
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

MIN_BRANCHES = 2

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")]
Label = Annotated[str, Field(min_length=1, max_length=200)]


class GraphValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors[:30]
        super().__init__("; ".join(self.errors))


class IrModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class SourceReference(IrModel):
    source_id: UUID
    quote: str = Field(min_length=1, max_length=1200)


class Grounded(IrModel):
    source: SourceReference | None = None
    assumption_of: str | None = Field(default=None, pattern=r"^Q-[1-9][0-9]*$")

    @model_validator(mode="after")
    def one_basis(self) -> "Grounded":
        if self.source and self.assumption_of:
            raise ValueError("Укажите цитату или допущение, а не оба основания")
        return self


class LaneIR(Grounded):
    id: Identifier
    name: Label


class NodeIR(Grounded):
    id: Identifier
    type: Literal["start", "end", "task", "xor", "and"]
    name: Label
    lane: Identifier
    task_kind: Literal[
        "task", "userTask", "manualTask", "sendTask", "receiveTask", "serviceTask"
    ] = "task"
    direction: Literal["split", "join"] | None = None
    join_id: Identifier | None = None
    event_kind: Literal["none", "message"] = "none"
    message_id: Identifier | None = None
    message_name: Label | None = None


class FlowIR(Grounded):
    id: Identifier
    source_id: Identifier
    target_id: Identifier
    name: str = Field(default="", max_length=200)
    condition: str | None = Field(default=None, min_length=1, max_length=500)
    default: bool = False


class GraphIR(IrModel):
    schema_version: Literal[1] = 1
    title: Label
    process_name: Label | None = None
    process_id: Identifier = "Process_1"
    participant_id: Identifier = "Participant_1"
    collaboration_id: Identifier = "Collaboration_1"
    lanes: list[LaneIR] = Field(min_length=1, max_length=30)
    nodes: list[NodeIR] = Field(min_length=2, max_length=100)
    flows: list[FlowIR] = Field(min_length=1, max_length=200)

    def canonical(self) -> dict[str, object]:
        """Стабильный audit JSON: перестановка массивов не меняет семантику."""
        value = self.model_dump(mode="json")
        for key in ("nodes", "flows"):
            value[key] = sorted(value[key], key=lambda item: item["id"])
        return value


def _walk(starts: set[str], edges: dict[str, set[str]], stop: set[str] | None = None) -> set[str]:
    seen: set[str] = set()
    pending = list(starts)
    while pending:
        item = pending.pop()
        if item in seen or item in (stop or set()):
            continue
        seen.add(item)
        pending.extend(edges.get(item, set()) - seen)
    return seen


def _validate_ids(graph: GraphIR, errors: list[str]) -> None:
    ids = [
        graph.process_id,
        graph.participant_id,
        graph.collaboration_id,
        *(x.id for x in graph.lanes),
        *(x.id for x in graph.nodes),
        *(x.id for x in graph.flows),
    ]
    ids += [
        x.message_id or f"Message_{x.id}"
        for x in graph.nodes
        if x.type == "start" and x.event_kind == "message"
    ]
    if len(set(ids)) != len(ids):
        errors.append("id: идентификаторы процесса, дорожек, узлов и потоков должны быть уникальны")
    reserved = {"Definitions_IR", "LaneSet_IR"}
    if reserved & set(ids):
        errors.append("id: служебные идентификаторы компилятора зарезервированы")


def _collect_links(
    graph: GraphIR,
    nodes: dict[str, NodeIR],
    *,
    outgoing: dict[str, list[FlowIR]],
    incoming: dict[str, list[FlowIR]],
    edges: dict[str, set[str]],
    reverse: dict[str, set[str]],
    errors: list[str],
) -> None:
    for i, flow in enumerate(graph.flows):
        if flow.source_id not in nodes or flow.target_id not in nodes:
            errors.append(f"flows.{i}: source_id/target_id ссылается на неизвестный узел")
            continue
        if flow.source_id == flow.target_id:
            errors.append(f"flows.{i}: прямой self-loop запрещён, используйте явный шлюз с выходом")
        outgoing[flow.source_id].append(flow)
        incoming[flow.target_id].append(flow)
        edges[flow.source_id].add(flow.target_id)
        reverse[flow.target_id].add(flow.source_id)
        owner = nodes[flow.source_id]
        if (flow.condition is not None or flow.default) and (
            owner.type != "xor" or owner.direction != "split"
        ):
            errors.append(f"flows.{i}: condition/default допускаются только на исходе XOR split")
        if flow.default and flow.condition:
            errors.append(f"flows.{i}: default-поток не должен иметь condition")


def validate_graph(graph: GraphIR) -> None:
    """Адресные ошибки структуры, включая топологию fork/join и выход из циклов."""
    errors: list[str] = []
    _validate_ids(graph, errors)
    nodes = {x.id: x for x in graph.nodes}
    lanes = {x.id for x in graph.lanes}
    outgoing: dict[str, list[FlowIR]] = defaultdict(list)
    incoming: dict[str, list[FlowIR]] = defaultdict(list)
    edges: dict[str, set[str]] = defaultdict(set)
    reverse: dict[str, set[str]] = defaultdict(set)
    _collect_links(
        graph,
        nodes,
        outgoing=outgoing,
        incoming=incoming,
        edges=edges,
        reverse=reverse,
        errors=errors,
    )
    starts = {x.id for x in graph.nodes if x.type == "start"}
    ends = {x.id for x in graph.nodes if x.type == "end"}
    if not starts or not ends:
        errors.append("nodes: нужны хотя бы один start и один end")
    if sum(x.type == "start" and x.event_kind == "none" for x in graph.nodes) > 1:
        errors.append(
            "nodes: допустим один blank start; альтернативы требуют явного message-события"
        )
    reached = _walk(starts, edges)
    ending = _walk(ends, reverse)
    for i, node in enumerate(graph.nodes):
        path = f"nodes.{i}({node.id})"
        if node.lane not in lanes:
            errors.append(f"{path}.lane: дорожка не существует")
        if node.id not in reached:
            errors.append(f"{path}: узел недостижим от начала")
        if node.id not in ending:
            errors.append(f"{path}: нет пути к завершению, цикл должен иметь выход")
        ins, outs = incoming[node.id], outgoing[node.id]
        _basic_node(node, path, ins, outs, errors)
        if node.type in {"xor", "and"}:
            _gateway(
                node,
                nodes,
                path=path,
                ins=ins,
                outs=outs,
                outgoing=outgoing,
                incoming=incoming,
                edges=edges,
                errors=errors,
            )
    for lane in lanes:
        if not any(node.lane == lane for node in graph.nodes):
            errors.append(f"lanes({lane}): пустая дорожка")
    if errors:
        raise GraphValidationError(errors)


def _basic_node(
    node: NodeIR, path: str, ins: list[FlowIR], outs: list[FlowIR], errors: list[str]
) -> None:
    if node.type != "task" and node.task_kind != "task":
        errors.append(f"{path}.task_kind: тип задачи допустим только у task")
    if node.type in {"start", "end", "task"} and (node.direction or node.join_id):
        errors.append(f"{path}: direction/join_id допустимы только у шлюза")
    if node.type == "start" and (ins or len(outs) != 1):
        errors.append(f"{path}: start имеет 0 входов и 1 выход; альтернативные старты не AND")
    if (node.message_id or node.message_name) and node.event_kind != "message":
        errors.append(f"{path}: message_id/name допустимы только у message-start")
    if node.event_kind != "none" and node.type != "start":
        errors.append(f"{path}.event_kind: тип события поддержан только у start")
    if node.type == "end" and (not ins or outs):
        errors.append(f"{path}: end имеет вход и не имеет выходов")
    if node.type == "task" and (len(ins) != 1 or len(outs) != 1):
        errors.append(f"{path}: у task ровно 1 вход/выход, объединяйте потоки явным шлюзом")


def _gateway(
    node: NodeIR,
    nodes: dict[str, NodeIR],
    *,
    path: str,
    ins: list[FlowIR],
    outs: list[FlowIR],
    outgoing: dict[str, list[FlowIR]],
    incoming: dict[str, list[FlowIR]],
    edges: dict[str, set[str]],
    errors: list[str],
) -> None:
    if node.direction == "split":
        if len(ins) != 1 or len(outs) < MIN_BRANCHES:
            errors.append(f"{path}: split требует 1 вход и минимум 2 выхода")
        if node.type == "xor":
            if sum(flow.default for flow in outs) > 1:
                errors.append(f"{path}: у XOR максимум один default")
            if any(not flow.name or (not flow.default and not flow.condition) for flow in outs):
                errors.append(f"{path}: каждый исход XOR подписан и имеет condition или default")
        else:
            _and_region(
                node,
                nodes,
                outgoing=outgoing,
                incoming=incoming,
                edges=edges,
                errors=errors,
                path=path,
            )
    elif node.direction == "join":
        if len(ins) < MIN_BRANCHES or len(outs) != 1 or node.join_id:
            errors.append(f"{path}: join требует минимум 2 входа, 1 выход и не имеет join_id")
        if node.type == "and" and not any(x.join_id == node.id for x in nodes.values()):
            errors.append(f"{path}: AND join не связан с соответствующим fork")
    else:
        errors.append(f"{path}.direction: шлюз должен быть split или join")


def _and_region(
    node: NodeIR,
    nodes: dict[str, NodeIR],
    *,
    outgoing: dict[str, list[FlowIR]],
    incoming: dict[str, list[FlowIR]],
    edges: dict[str, set[str]],
    errors: list[str],
    path: str,
) -> None:
    join = nodes.get(node.join_id or "")
    if node.join_id and (join is None or join.type != "and" or join.direction != "join"):
        errors.append(f"{path}.join_id: должен указывать на AND join")
        return
    branches: list[set[str]] = []
    arrival: set[str] = set()
    for flow in outgoing[node.id]:
        region = _walk({flow.target_id}, edges, {node.join_id} if node.join_id else set())
        if node.id in region:
            errors.append(f"{path}: ветвь возвращается в собственный AND fork до join")
        if any(region & previous for previous in branches):
            errors.append(
                f"{path}: параллельные ветви сливаются до указанного join/раздельных ends"
                + (
                    "; у fork отсутствует join_id — укажи id соответствующего AND join, "
                    "если ветви должны синхронизироваться"
                    if not node.join_id
                    else ""
                )
            )
        branches.append(region)
        if join:
            arrivals = [
                f.id for member in region for f in outgoing[member] if f.target_id == join.id
            ]
            if flow.target_id == join.id:
                arrivals.append(flow.id)
            if len(arrivals) != 1 or any(nodes[x].type == "end" for x in region):
                errors.append(
                    f"{path}: каждая AND-ветвь должна дать ровно один вход join, без раннего end"
                )
            arrival.update(arrivals)
            # Нельзя войти в ветвь из другой части графа — join иначе ждёт не тот набор токенов.
            for member in region:
                if any(f.source_id not in region and f.id != flow.id for f in incoming[member]):
                    errors.append(f"{path}: внешний поток входит в параллельную ветвь")
        elif not any(nodes[x].type == "end" for x in region):
            errors.append(f"{path}: fork без join допустим только с раздельными ends каждой ветви")
    if join and arrival != {f.id for f in incoming[join.id]}:
        errors.append(f"{path}: входы join не совпадают с выходами ветвей fork")
