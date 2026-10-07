"""Записанный отказ Pro: Markdown-цитаты и скрытые до grounding ошибки топологии."""

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.domain.analysis import AnalysisResult, ContextSource, RunContext
from app.domain.models import SourceKind
from app.fixtures import read_text
from app.llm.base import PipelineError
from app.llm.openai_compatible import OpenAICompatiblePipeline
from tests.test_graph_ir import SOURCE_ID, TEXT, graph_case

RECORDED = Path(__file__).parent / "fixtures" / "logistics_order_bad_ir.json"


def _context(content: str, source_id: UUID = SOURCE_ID) -> RunContext:
    return RunContext(
        project_id=uuid4(),
        project_title="Проверка repair",
        sources=[
            ContextSource(
                id=source_id,
                title="Регламент",
                kind=SourceKind.TEXT,
                content=content,
                created_at=datetime.now(UTC),
            )
        ],
        questions=[],
    )


async def test_recorded_pro_failure_exposes_literal_and_topology_hints_without_repairing_graph():
    broken = json.loads(RECORDED.read_text(encoding="utf-8"))
    before = deepcopy(broken)
    source_id = UUID(broken["nodes"][1]["source"]["source_id"])
    content = read_text("logistics_order.md")
    prompts = []

    def complete(_system, prompt):
        prompts.append(json.loads(prompt))
        return json.dumps(broken)

    pipeline = OpenAICompatiblePipeline(api_key="recorded-only", complete=complete)
    with pytest.raises(PipelineError, match="трёх исправлений"):
        await pipeline.structure(_context(content, source_id), AnalysisResult())
    assert len(prompts) == 4
    assert "repair_hints" not in prompts[0]
    assert broken == before
    assert prompts[1]["draft"] == broken
    hints = prompts[1]["repair_hints"]
    assert len(hints["literal_sources"]) <= 12
    assert len(hints["topology"]) <= 8
    for hint in hints["literal_sources"]:
        assert hint["source_id"] == str(source_id)
        assert hint["literal_fragment"] in content
        assert len(hint["literal_fragment"]) <= 480
    first = next(hint for hint in hints["literal_sources"] if hint["path"] == "nodes.1.source")
    assert (
        "**Зарегистрировать состав заказа и адрес доставки.** Ответственный:"
        in first["literal_fragment"]
    )
    topology = {hint["element_id"]: hint for hint in hints["topology"]}
    fork = topology["And_FeasibilitySplit"]
    assert fork["join_id"] is None
    assert fork["reachable_and_joins"][0]["id"] == "And_FeasibilityJoin"
    assert len(fork["outgoing"]) == 3
    assert len(topology["Task_CheckDetails"]["incoming"]) == 2
    assert any("ровно 1 вход/выход" in error for error in topology["Task_CheckDetails"]["errors"])


async def test_only_explicit_corrected_model_response_can_use_literal_candidate():
    paragraph = "**Проверить заявку.** Ответственный: Оператор. Проверяет комплект документов."
    context = _context(TEXT + "\n\n" + paragraph)
    broken = graph_case("xor")
    task = next(node for node in broken["nodes"] if node["id"] == "Check")
    task["name"] = "Проверить заявку"
    task["source"] = {
        "source_id": str(SOURCE_ID),
        "quote": "Проверить заявку. Ответственный: Оператор.",
    }
    prompts = []

    def complete(_system, prompt):
        payload = json.loads(prompt)
        prompts.append(payload)
        if len(prompts) == 1:
            return json.dumps(broken)
        hint = next(
            hint
            for hint in payload["repair_hints"]["literal_sources"]
            if hint["element_id"] == "Check"
        )
        corrected = deepcopy(broken)
        corrected_task = next(node for node in corrected["nodes"] if node["id"] == "Check")
        corrected_task["source"]["quote"] = hint["literal_fragment"]
        return json.dumps(corrected)

    draft = await OpenAICompatiblePipeline(api_key="recorded-only", complete=complete).structure(
        context, AnalysisResult()
    )
    assert len(prompts) == 2
    assert draft.trace["Check"].source_id == SOURCE_ID
    assert draft.trace["Check"].quote == paragraph
    assert task["source"]["quote"] == "Проверить заявку. Ответственный: Оператор."


@pytest.mark.parametrize("known_source", [False, True])
async def test_feedback_never_searches_another_source_or_replaces_the_claimed_id(known_source):
    context = _context(TEXT)
    another_id = uuid4()
    context.sources.append(
        ContextSource(
            id=another_id,
            title="Другой документ",
            kind=SourceKind.TEXT,
            content="**Проверить заявку.** Ответственный: Оператор.",
            created_at=datetime.now(UTC),
        )
    )
    broken = graph_case("xor")
    task = next(node for node in broken["nodes"] if node["id"] == "Check")
    task["name"] = "Проверить заявку"
    claimed_id = SOURCE_ID if known_source else uuid4()
    task["source"] = {"source_id": str(claimed_id), "quote": "Проверить заявку."}
    prompts = []

    def complete(_system, prompt):
        prompts.append(json.loads(prompt))
        return json.dumps(broken)

    with pytest.raises(PipelineError, match="трёх исправлений"):
        await OpenAICompatiblePipeline(api_key="recorded-only", complete=complete).structure(
            context, AnalysisResult()
        )
    assert len(prompts) == 4
    for prompt in prompts[1:]:
        candidates = prompt["repair_hints"].get("literal_sources", [])
        assert not [hint for hint in candidates if hint["element_id"] == "Check"]
        assert next(node for node in prompt["draft"]["nodes"] if node["id"] == "Check")["source"][
            "source_id"
        ] == str(claimed_id)
