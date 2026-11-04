"""Смысловая проверка требует основание и запускает repair до публикации."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.domain.analysis import AnalysisResult
from app.domain.bpmn.ir import GraphIR
from app.domain.models import Question, QuestionKind, QuestionStatus, Severity
from app.llm.base import CachedPrefixPrompt, PipelineError
from app.llm.semantic_review import _review_part, review_semantics
from tests.llm_helpers import ScriptedPipeline
from tests.test_graph_ir import SOURCE_ID, TEXT, graph_case
from tests.test_graph_repair_feedback import _context


async def test_unverifiable_semantic_issue_never_passes_as_success():
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

    report = await review_semantics(
        GraphIR.model_validate(graph_case("xor")), _context(TEXT), complete
    )
    # Неподтверждённый отчёт не ошибка графа и не «ошибок нет»: порция не проверена.
    assert report.errors == []
    assert report.unchecked_parts == 1


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

    draft = await ScriptedPipeline(
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


def _issue(message: str) -> str:
    return json.dumps(
        {
            "issues": [
                {
                    "element_id": "Check",
                    "source_id": str(SOURCE_ID),
                    "quote": TEXT[:30],
                    "message": message,
                }
            ]
        }
    )


async def test_persistent_semantic_issues_publish_graph_with_report_warnings():
    # Сверка находит замечания каждый раз: схема всё равно публикуется после второго круга,
    # а незакрытые замечания уходят в предупреждения отчёта (раньше — сбой всей сборки).
    reviews = 0
    generations = 0

    def complete(system, _prompt):
        nonlocal reviews, generations
        if "независимо от автора" in system:
            reviews += 1
            return _issue(f"Пропущено действие {reviews}")
        generations += 1
        return json.dumps(graph_case("xor"))

    draft = await ScriptedPipeline(
        api_key="recorded-only", complete=complete, semantic_review=True
    ).structure(_context(TEXT), AnalysisResult())
    assert draft.ir is not None
    assert reviews == 2
    assert generations == 2
    assert any("Пропущено действие 2" in warning for warning in draft.warnings)
    assert all("Пропущено действие 1" not in warning for warning in draft.warnings)


async def test_broken_repair_falls_back_to_last_checked_graph():
    # Исправление по замечаниям сверки ломает структуру во всех оставшихся попытках:
    # публикуется последний проверенный граф с замечаниями первого круга.
    generations = 0

    def complete(system, _prompt):
        nonlocal generations
        if "независимо от автора" in system:
            return _issue("Неверный порядок действий")
        generations += 1
        return json.dumps(graph_case("xor")) if generations == 1 else "{}"

    draft = await ScriptedPipeline(
        api_key="recorded-only", complete=complete, semantic_review=True
    ).structure(_context(TEXT), AnalysisResult())
    assert draft.ir == GraphIR.model_validate(graph_case("xor")).canonical()
    assert generations == 4
    assert any("Неверный порядок" in warning for warning in draft.warnings)


async def test_repair_prompt_keeps_sources_as_cached_prefix():
    prompts: list[str] = []

    def complete(system, prompt):
        if "независимо от автора" in system:
            return _issue("Неверный порядок действий") if len(prompts) == 1 else '{"issues": []}'
        prompts.append(prompt)
        return json.dumps(graph_case("xor"))

    await ScriptedPipeline(
        api_key="recorded-only", complete=complete, semantic_review=True
    ).structure(_context(TEXT), AnalysisResult())
    first, repair = prompts
    assert isinstance(repair, CachedPrefixPrompt)
    # Источники и вопросы — общее начало обеих попыток: провайдер берёт его из кеша.
    assert repair.prefix == first[:-1]
    assert json.loads(repair)["errors"]
