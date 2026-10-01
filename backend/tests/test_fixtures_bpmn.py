"""BPMN-фикстуры и примеры проходят официальные XSD OMG; цитаты правил есть в текстах."""

from pathlib import Path

import pytest
from lxml import etree

from app.domain.bpmn.document import parse_bpmn
from app.domain.bpmn.linear import LinearStep, build_linear_diagram
from app.domain.bpmn.lint import lint_document
from app.domain.bpmn.xsd import XSD_ENTRY
from app.domain.questions import quote_in_source
from app.fixtures import BPMN_DIR, TEXTS_DIR, bpmn_names, read_bpmn, read_text
from app.fixtures.catalog import TOPICS
from app.fixtures.generic import generic_questions, meeting_note, regulation_text
from app.fixtures.playbook import (
    PERMIT_ANSWER_REMARKS,
    PLAYBOOK,
    PROCUREMENT_ANSWER_PLAN,
    SUPPLY_NOTE,
    TP_ANSWER_TERM,
)
from app.fixtures.types import Topic

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
SCHEMA = etree.XMLSchema(etree.parse(str(XSD_ENTRY)))
ALL_TEXT = "\n".join(
    [read_text(p.name) for p in TEXTS_DIR.iterdir()]
    + [SUPPLY_NOTE, TP_ANSWER_TERM, PERMIT_ANSWER_REMARKS, PROCUREMENT_ANSWER_PLAN]
)


def _xsd_errors(xml: str) -> str:
    document = etree.fromstring(xml.encode("utf-8"))
    return "" if SCHEMA.validate(document) else str(SCHEMA.error_log)


@pytest.mark.parametrize("name", bpmn_names())
def test_fixture_is_xsd_valid_and_complete(name: str) -> None:
    xml = read_bpmn(name)
    assert _xsd_errors(xml) == ""
    document = parse_bpmn(xml)
    assert document.has_layout
    assert document.participants
    assert len(document.lanes) >= 3
    for node in document.nodes.values():
        assert node.lane_id, f"{name}: {node.id} без дорожки"
    errors = [issue for issue in lint_document(document) if issue.severity == "error"]
    assert errors == []


def test_examples_are_copies_of_fixtures() -> None:
    files = sorted(EXAMPLES.rglob("*.bpmn"))
    assert len(files) == 5
    fixtures = {path.read_text(encoding="utf-8") for path in BPMN_DIR.glob("*.bpmn")}
    for path in files:
        xml = path.read_text(encoding="utf-8")
        assert _xsd_errors(xml) == ""
        assert xml in fixtures


def test_demo_diagram_has_xor_and_parallel_and_loop() -> None:
    document = parse_bpmn(read_bpmn("tp861_v2"))
    types = {node.type for node in document.nodes.values()}
    assert {"exclusiveGateway", "parallelGateway", "startEvent", "endEvent"} <= types
    loop_back = [f for f in document.flows if f.source == "Task_AddDocuments"]
    assert loop_back[0].target == "Gateway_CheckMerge"
    labels = {f.name for f in document.flows if f.source == "Gateway_Power"}
    assert labels == {"Да", "Нет"}


def test_playbook_quotes_exist_in_fixture_texts() -> None:
    quotes = [rule.trigger for rule in PLAYBOOK.questions]
    quotes += [rule.evidence for rule in PLAYBOOK.resolutions]
    for diagram in PLAYBOOK.diagrams:
        quotes += list(diagram.requires) + list(diagram.trace.values())
        ids = parse_bpmn(read_bpmn(diagram.fixture)).element_ids
        assert set(diagram.trace) <= ids, diagram.fixture
    missing = [quote for quote in quotes if not quote_in_source(quote, ALL_TEXT)]
    assert missing == []


def test_question_element_ids_exist_in_some_diagram() -> None:
    ids = set().union(*(parse_bpmn(read_bpmn(name)).element_ids for name in bpmn_names()))
    for rule in PLAYBOOK.questions:
        assert set(rule.element_ids) <= ids, rule.text


@pytest.mark.parametrize("topic", TOPICS[:6], ids=lambda t: t.key)
def test_generated_linear_diagrams_are_xsd_valid(topic: Topic) -> None:
    xml = build_linear_diagram(
        process_name=topic.title,
        steps=[LinearStep(name=task, lane=role) for role, task in topic.steps],
    )
    assert _xsd_errors(xml) == ""
    assert lint_document(parse_bpmn(xml)) == []
    text = regulation_text(topic)
    for item in generic_questions([task for _, task in topic.steps]):
        assert quote_in_source(item.rule.trigger, text)
    assert "«" in meeting_note(topic)


def test_linear_builder_requires_steps() -> None:
    with pytest.raises(ValueError, match="шаг"):
        build_linear_diagram(process_name="Пусто", steps=[])
