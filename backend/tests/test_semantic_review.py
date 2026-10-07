"""Смысловая проверка требует основание и запускает repair до публикации."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.domain.analysis import AnalysisResult
from app.domain.bpmn.ir import GraphIR
from app.domain.models import Question, QuestionKind, QuestionStatus, Severity
from app.llm.base import PipelineError
from app.llm.openai_compatible import OpenAICompatiblePipeline
from app.llm.semantic_review import _review_part, review_semantics
from tests.test_graph_ir import SOURCE_ID, TEXT, graph_case
from tests.test_graph_repair_feedback import _context


async def test_unverifiable_semantic_issue_never_passes():
    async def complete(_system, _prompt):
        return json.dumps(
            {
                "issues": [
                    {
                        "element_id": "Check",
                        "source_id": str(SOURCE_ID),
                        "quote": "Выдумано",
                        "message": "Ошибка",
                    }
                ]
            }
        )

    with pytest.raises(PipelineError, match="смысловой"):
        await review_semantics(GraphIR.model_validate(graph_case("xor")), _context(TEXT), complete)


async def test_semantic_issue_enters_repair_and_only_checked_graph_is_returned():
    reviews = 0
    generations = []

    def complete(system, prompt):
        nonlocal reviews
        data = json.loads(prompt)
        if "независимо от автора" in system:
            reviews += 1
            return json.dumps(
                {
                    "issues": [
                        {
                            "element_id": "Check",
                            "source_id": str(SOURCE_ID),
                            "quote": TEXT[:30],
                            "message": "Неверный порядок действий",
                        }
                    ]
                    if reviews == 1
                    else []
                }
            )
        generations.append(data)
        return json.dumps(graph_case("xor"))

    draft = await OpenAICompatiblePipeline(
        api_key="recorded-only", complete=complete, semantic_review=True
    ).structure(_context(TEXT), AnalysisResult())
    assert draft.ir is not None
    assert reviews == 2
    assert len(generations) == 2
    assert "Неверный порядок" in generations[1]["errors"][0]


async def test_semantic_review_rejects_quote_outside_current_part():
    context = _context(TEXT)
    context = replace(
        context,
        sources=[replace(context.sources[0], content="Другая порция")],
        evidence_sources=context.sources,
    )

    async def complete(_system, _prompt):
        return json.dumps(
            {
                "issues": [
                    {
                        "element_id": "Check",
                        "source_id": str(SOURCE_ID),
                        "quote": TEXT[:30],
                        "message": "Ошибка",
                    }
                ]
            }
        )

    with pytest.raises(PipelineError, match="смысловой"):
        await _review_part(GraphIR.model_validate(graph_case("xor")), context, complete)


async def test_review_excludes_superseded_assumptions():
    context = _context(TEXT)
    now = datetime.now(UTC)
    context.questions = [
        Question(
            id=uuid4(),
            project_id=context.project_id,
            code=f"Q-{i}",
            kind=QuestionKind.MISSING_ACTOR,
            severity=Severity.MAJOR,
            status=status,
            text="Кто?",
            assumption="Оператор",
            created_at=now,
            updated_at=now,
        )
        for i, status in enumerate(QuestionStatus)
    ]
    seen = []

    async def complete(_system, prompt):
        seen.extend(json.loads(prompt)["assumptions"])
        return '{"issues": []}'

    await review_semantics(GraphIR.model_validate(graph_case("xor")), context, complete)
    assert {item["code"] for item in seen} == {"Q-0", "Q-2"}
