"""Компилятор/семантика IR v1, официальный XSD и записанный формат ответа адаптера."""

import json
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from lxml import etree

from app.domain.analysis import AnalysisResult, ContextSource, RunContext
from app.domain.bpmn.compiler import compile_graph
from app.domain.bpmn.importer import import_graph, retain_trace
from app.domain.bpmn.ir import GraphIR, GraphValidationError, validate_graph
from app.domain.bpmn.xsd import XSD_ENTRY
from app.domain.models import (
    Answer,
    Question,
    QuestionKind,
    QuestionStatus,
    Quote,
    Severity,
    SourceKind,
)
from app.fixtures import read_bpmn
from app.llm.base import PipelineError
from app.llm.openai_compatible import OpenAICompatiblePipeline

SOURCE_ID = UUID("11111111-1111-4111-8111-111111111111")
TEXT = (
    "Оператор проверяет заявку. Если документы полные, оператор согласует её, "
    "иначе возвращает на доработку. Бухгалтерия и экономист одновременно согласуют оплату. "
    "Заявка приходит через портал или письмом."
)
PROOF = {"source_id": str(SOURCE_ID), "quote": TEXT}


def node(key: str, kind: str = "task", lane: str = "Operator", **kwargs: Any) -> dict[str, Any]:
    return {"id": key, "type": kind, "name": key, "lane": lane, "source": PROOF, **kwargs}


def flow(key: str, from_id: str, target: str, **kwargs: Any) -> dict[str, Any]:
    return {"id": key, "source_id": from_id, "target_id": target, **kwargs}


def graph_case(case: str = "xor") -> dict[str, Any]:
    lanes = [{"id": "Operator", "name": "Оператор", "source": PROOF}]
    if case == "xor":
        nodes = [
            node("Start", "start"),
            node("Check"),
            node("Decision", "xor", direction="split"),
            node("Accept"),
            node("Reject"),
            node("Merge", "xor", direction="join"),
            node("End", "end"),
        ]
        flows = [
            flow("F1", "Start", "Check"),
            flow("F2", "Check", "Decision"),
            flow(
                "Yes", "Decision", "Accept", name="Да", condition="Документы полные", source=PROOF
            ),
            flow("No", "Decision", "Reject", name="Нет", default=True, source=PROOF),
            flow("F3", "Accept", "Merge"),
            flow("F4", "Reject", "Merge"),
            flow("F5", "Merge", "End"),
        ]
    elif case == "loop":
        nodes = [
            node("Start", "start"),
            node("Merge", "xor", direction="join"),
            node("Check"),
            node("Decision", "xor", direction="split"),
            node("Rework"),
            node("End", "end"),
        ]
        flows = [
            flow("F1", "Start", "Merge"),
            flow("F2", "Merge", "Check"),
            flow("F3", "Check", "Decision"),
            flow("Yes", "Decision", "End", name="Да", condition="Документы полные", source=PROOF),
            flow("No", "Decision", "Rework", name="Нет", default=True, source=PROOF),
            flow("Back", "Rework", "Merge"),
        ]
    elif case in {"and", "nested", "parallel_ends"}:
        lanes += [
            {"id": "Accounting", "name": "Бухгалтерия", "source": PROOF},
            {"id": "Economist", "name": "Экономист", "source": PROOF},
        ]
        nodes = [
            node("Start", "start"),
            node(
                "Fork",
                "and",
                direction="split",
                join_id=None if case == "parallel_ends" else "Join",
            ),
            node("AccountingTask", lane="Accounting"),
            node("EconomistTask", lane="Economist"),
        ]
        flows = [
            flow("F1", "Start", "Fork"),
            flow("FA", "Fork", "AccountingTask"),
            flow("FB", "Fork", "EconomistTask"),
        ]
        if case == "parallel_ends":
            nodes += [node("EndA", "end", lane="Accounting"), node("EndB", "end", lane="Economist")]
            flows += [flow("FEA", "AccountingTask", "EndA"), flow("FEB", "EconomistTask", "EndB")]
        else:
            nodes += [node("Join", "and", direction="join"), node("End", "end")]
            flows += [
                flow("FAJ", "AccountingTask", "Join"),
                flow("FBJ", "EconomistTask", "Join"),
                flow("FE", "Join", "End"),
            ]
        if case == "nested":
            nodes += [
                node("Decision", "xor", lane="Accounting", direction="split"),
                node("Accept", lane="Accounting"),
                node("Reject", lane="Accounting"),
                node("Merge", "xor", lane="Accounting", direction="join"),
            ]
            flows = [f for f in flows if f["id"] != "FAJ"] + [
                flow("FAD", "AccountingTask", "Decision"),
                flow(
                    "Yes",
                    "Decision",
                    "Accept",
                    name="Да",
                    condition="Документы полные",
                    source=PROOF,
                ),
                flow("No", "Decision", "Reject", name="Нет", default=True, source=PROOF),
                flow("FAM", "Accept", "Merge"),
                flow("FRM", "Reject", "Merge"),
                flow("FAJ", "Merge", "Join"),
            ]
    elif case == "starts":
        nodes = [
            node("Portal", "start", event_kind="message", name="Портал"),
            node("Letter", "start", event_kind="message", name="Письмо"),
            node("Merge", "xor", direction="join"),
            node("Check"),
            node("End", "end"),
        ]
        flows = [
            flow("FP", "Portal", "Merge"),
            flow("FL", "Letter", "Merge"),
            flow("F1", "Merge", "Check"),
            flow("FE", "Check", "End"),
        ]
    else:
        raise ValueError(case)
    return {
        "schema_version": 1,
        "title": "Проверка заявки",
        "lanes": lanes,
        "nodes": nodes,
        "flows": flows,
    }


@pytest.mark.parametrize("case", ["xor", "loop", "and", "nested", "starts", "parallel_ends"])
def test_compile_real_graph_and_xsd(case):
    graph = GraphIR.model_validate(graph_case(case))
    validate_graph(graph)
    xml = compile_graph(graph)
    schema = etree.XMLSchema(etree.parse(str(XSD_ENTRY)))
    assert schema.validate(etree.fromstring(xml.encode())), schema.error_log
    imported = import_graph(xml)
    validate_graph(imported)
    assert {n.id for n in imported.nodes} == {n.id for n in graph.nodes}
    assert {(f.id, f.source_id, f.target_id, f.default, f.condition) for f in imported.flows} == {
        (f.id, f.source_id, f.target_id, f.default, f.condition) for f in graph.flows
    }


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda g: g["flows"][0].update(target_id="Missing"), "source_id/target_id"),
        (lambda g: g["nodes"][0].update(id="Check"), "уникальны"),
        (lambda g: g["flows"][2].update(condition=None), "condition"),
        (lambda g: g["nodes"][3].update(lane="Missing"), "дорожка"),
        (lambda g: g["flows"][4].update(target_id="Check"), "task"),
    ],
)
def test_addressed_semantic_errors(mutation, match):
    data = deepcopy(graph_case())
    mutation(data)
    with pytest.raises(GraphValidationError, match=match):
        validate_graph(GraphIR.model_validate(data))


def test_and_join_rejects_xor_paths_as_two_parallel_arrivals():
    data = graph_case("nested")
    data["flows"] = [f for f in data["flows"] if f["id"] not in {"FAM", "FRM", "FAJ"}]
    data["flows"] += [flow("FAM", "Accept", "Join"), flow("FRM", "Reject", "Join")]
    with pytest.raises(GraphValidationError, match=r"ровно один вход|недостижим"):
        validate_graph(GraphIR.model_validate(data))


def test_message_definition_id_cannot_collide_with_a_task():
    data = graph_case("starts")
    data["nodes"][3]["id"] = "Message_Portal"
    with pytest.raises(GraphValidationError, match="уникальны"):
        validate_graph(GraphIR.model_validate(data))


@pytest.mark.asyncio
async def test_recorded_adapter_response_ir_and_citations():
    source = ContextSource(
        id=SOURCE_ID,
        kind=SourceKind.TEXT,
        title="Регламент",
        content=TEXT,
        created_at=datetime.now(UTC),
    )
    context = RunContext(project_id=uuid4(), project_title="Заявка", sources=[source], questions=[])
    pipeline = OpenAICompatiblePipeline(
        api_key="test-only",
        complete=lambda _s, _p: json.dumps(graph_case("nested"), ensure_ascii=False),
    )
    result = await pipeline.structure(context, AnalysisResult())
    assert result.ir
    assert any(n["type"] == "and" for n in result.ir["nodes"])
    assert "parallelGateway" in result.xml
    assert "exclusiveGateway" in result.xml
    assert result.trace["AccountingTask"].quote == TEXT


@pytest.mark.asyncio
async def test_three_repairs_then_failure_without_draft():
    source = ContextSource(
        id=SOURCE_ID,
        kind=SourceKind.TEXT,
        title="Регламент",
        content=TEXT,
        created_at=datetime.now(UTC),
    )
    calls = []
    invalid = graph_case()
    invalid["flows"][0]["target_id"] = "Missing"

    def complete(_system, prompt):
        calls.append(json.loads(prompt))
        return json.dumps(invalid)

    pipeline = OpenAICompatiblePipeline(api_key="test-only", complete=complete)
    with pytest.raises(PipelineError, match="трёх исправлений"):
        await pipeline.structure(
            RunContext(project_id=uuid4(), project_title="Заявка", sources=[source], questions=[]),
            AnalysisResult(),
        )
    assert len(calls) == 4
    assert calls[-1]["errors"]


def test_provenance_ignores_serializer_whitespace_and_attribute_order():
    xml = compile_graph(GraphIR.model_validate(graph_case()))
    moved = xml.replace('id="Check" name="Check"', 'name="Check" id="Check"').replace("  ", "    ")
    citation = Quote(source_id=SOURCE_ID, quote=TEXT)
    assert retain_trace(xml, moved, {"Check": citation}) == {"Check": citation}
    assert (
        retain_trace(
            xml, moved.replace('name="Check"', 'name="Новое действие"'), {"Check": citation}
        )
        == {}
    )


@pytest.mark.parametrize("extra", ['isForCompensation="true"', 'implementation="handler"'])
def test_opaque_manual_attributes_are_not_lost(extra):
    xml = compile_graph(GraphIR.model_validate(graph_case()))
    with pytest.raises(GraphValidationError, match="вне IR"):
        import_graph(xml.replace('<bpmn:task id="Check"', f'<bpmn:task {extra} id="Check"'))


@pytest.mark.asyncio
async def test_open_assumption_has_real_node_binding_and_short_answer_has_question_context():

    now = datetime.now(UTC)
    q = Question(
        id=uuid4(),
        project_id=uuid4(),
        code="Q-1",
        kind=QuestionKind.MISSING_ACTOR,
        severity=Severity.MAJOR,
        status=QuestionStatus.OPEN,
        text="Кто готовит акт?",
        assumption="Инженер",
        created_at=now,
        updated_at=now,
    )
    source = ContextSource(
        id=SOURCE_ID, kind=SourceKind.TEXT, title="Регламент", content=TEXT, created_at=now
    )
    data = graph_case()
    check = next(n for n in data["nodes"] if n["id"] == "Check")
    check.pop("source")
    check["assumption_of"] = "Q-1"
    seen = []

    def complete(_system, prompt):
        seen.append(json.loads(prompt))
        return json.dumps(data)

    pipeline = OpenAICompatiblePipeline(api_key="test-only", complete=complete)
    context = RunContext(
        project_id=q.project_id, project_title="Заявка", sources=[source], questions=[q]
    )
    draft = await pipeline.structure(context, AnalysisResult())
    assert draft.bindings == {"Q-1": ["Check"]}
    q.status = QuestionStatus.ANSWERED
    q.answer = Answer(source_id=SOURCE_ID, text="Инженер")
    check.pop("assumption_of")
    check["source"] = PROOF
    await pipeline.structure(context, AnalysisResult())
    assert seen[-1]["questions"][0]["text"] == "Кто готовит акт?"
    assert seen[-1]["questions"][0]["answer"]["text"] == "Инженер"


def test_legacy_fixture_task_subtypes_are_imported_without_flattening():

    graph = import_graph(read_bpmn("tp861_v2"))
    assert any(node.task_kind == "sendTask" for node in graph.nodes)
    assert any(node.type == "and" for node in graph.nodes)
    xml = compile_graph(graph)
    assert "sendTask" in xml
