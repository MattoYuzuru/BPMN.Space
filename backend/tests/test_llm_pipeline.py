import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.domain.analysis import AnalysisResult, ContextSource, RunContext
from app.domain.models import SourceKind
from app.llm.base import PipelineError
from app.llm.pipeline import _verified_quote
from tests.llm_helpers import ScriptedPipeline

_NO_SLEEP = lambda _seconds: None  # noqa: E731 — тесты не ждут настоящих пауз


def test_verified_quote_accepts_pdf_line_wraps_and_returns_verbatim_source() -> None:
    source_id = uuid4()
    source = ContextSource(
        id=source_id,
        kind=SourceKind.TEXT,
        title="Инструкция",
        content="Сотрудник проверяет комплектность документов:\n«Лист сверки с учётом даты». ",
        created_at=datetime.now(UTC),
    )

    verified_id, excerpt = _verified_quote(
        [source],
        str(source_id),
        "СОТРУДНИК проверяет комплектность документов: «Лист сверки с учетом даты».",
    )

    assert verified_id == source_id
    assert excerpt == "Сотрудник проверяет комплектность документов:\n«Лист сверки с учётом даты»."


def test_verified_quote_rejects_a_fabricated_suffix_after_a_long_valid_prefix() -> None:
    source = ContextSource(
        id=uuid4(),
        kind=SourceKind.TEXT,
        title="Регламент",
        content="а" * 1200,
        created_at=datetime.now(UTC),
    )
    assert _verified_quote([source], str(source.id), source.content + " ВЫДУМАННЫЙ ФАКТ") == (
        None,
        None,
    )


def test_verified_quote_preserves_a_fact_after_expanded_pdf_whitespace() -> None:
    source = ContextSource(
        id=uuid4(),
        kind=SourceKind.TEXT,
        title="PDF регламент",
        content="Инженер" + " " * 1300 + "готовит акт.",
        created_at=datetime.now(UTC),
    )
    assert _verified_quote([source], str(source.id), "Инженер готовит акт.") == (
        source.id,
        source.content,
    )


@pytest.mark.asyncio
async def test_pipeline_builds_diagram_and_keeps_only_verifiable_quotes() -> None:
    source_id = uuid4()
    source = ContextSource(
        id=source_id,
        kind=SourceKind.TEXT,
        title="Инструкция",
        content="Оператор проверяет комплектность документов. Руководитель согласует заявку.",
        created_at=datetime.now(UTC),
    )
    context = RunContext(
        project_id=uuid4(),
        project_title="Согласование заявки",
        sources=[source],
        questions=[],
    )

    def recorded_ir(quote: str) -> dict:
        first = {
            "source_id": str(source_id),
            "quote": "Оператор проверяет комплектность документов.",
        }
        second = {"source_id": str(source_id), "quote": quote}
        return {
            "schema_version": 1,
            "title": context.project_title,
            "lanes": [
                {"id": "Operator", "name": "Оператор", "source": first},
                {
                    "id": "Manager",
                    "name": "Руководитель",
                    "source": {
                        "source_id": str(source_id),
                        "quote": "Руководитель согласует заявку.",
                    },
                },
            ],
            "nodes": [
                {"id": "Start", "type": "start", "name": "Начало", "lane": "Operator"},
                {
                    "id": "Task_1",
                    "type": "task",
                    "name": "Проверить комплектность документов",
                    "lane": "Operator",
                    "source": first,
                },
                {
                    "id": "Task_2",
                    "type": "task",
                    "name": "Согласовать заявку",
                    "lane": "Manager",
                    "source": second,
                },
                {"id": "End", "type": "end", "name": "Завершение", "lane": "Manager"},
            ],
            "flows": [
                {"id": "F1", "source_id": "Start", "target_id": "Task_1"},
                {"id": "F2", "source_id": "Task_1", "target_id": "Task_2"},
                {"id": "F3", "source_id": "Task_2", "target_id": "End"},
            ],
        }

    responses = iter(
        [
            json.dumps(
                {
                    "complete": True,
                    "question_updates": [],
                    "new_questions": [
                        {
                            "kind": "missing_outcome",
                            "severity": "major",
                            "text": "Что происходит после согласования?",
                            "assumption": "Процесс завершается",
                            "source_id": str(source_id),
                            "quote": "Руководитель согласует заявку.",
                        }
                    ],
                }
            ),
            json.dumps(
                {
                    "complete": True,
                    "decisions": [
                        {"id": "N-1", "valid": True, "reason": "Результат согласования не описан"}
                    ],
                }
            ),
            json.dumps(recorded_ir("Цитата, которой нет в источнике.")),
            json.dumps(recorded_ir("Руководитель согласует заявку.")),
        ]
    )
    pipeline = ScriptedPipeline(
        api_key="test-only", complete=lambda _system, _prompt: next(responses)
    )

    analysis = await pipeline.analyze(context)
    draft = await pipeline.structure(context, analysis)

    assert len(analysis.new_questions) == 1
    assert analysis.new_questions[0].about is not None
    assert "bpmn:process" in draft.xml
    assert "Проверить комплектность документов" in draft.xml
    assert {"Task_1", "Task_2"} <= set(draft.trace)
    assert draft.trace["Task_1"].quote == "Оператор проверяет комплектность документов."
    assert draft.trace["Task_2"].quote == "Руководитель согласует заявку."


@pytest.mark.asyncio
async def test_pipeline_refuses_steps_without_source_quotes_after_repair() -> None:
    source_id = uuid4()
    context = RunContext(
        project_id=uuid4(),
        project_title="Согласование заявки",
        sources=[
            ContextSource(
                id=source_id,
                kind=SourceKind.TEXT,
                title="Инструкция",
                content="Оператор проверяет комплектность документов.",
                created_at=datetime.now(UTC),
            )
        ],
        questions=[],
    )
    response = json.dumps(
        {
            "schema_version": 1,
            "title": "Согласование",
            "lanes": [
                {
                    "id": "Operator",
                    "name": "Оператор",
                    "source": {
                        "source_id": str(source_id),
                        "quote": "Оператор проверяет комплектность документов.",
                    },
                }
            ],
            "nodes": [
                {"id": "Start", "type": "start", "name": "Начало", "lane": "Operator"},
                {
                    "id": "Task",
                    "type": "task",
                    "name": "Отправить договор",
                    "lane": "Operator",
                    "source": {"source_id": str(source_id), "quote": "Цитаты в источнике нет."},
                },
                {"id": "End", "type": "end", "name": "Конец", "lane": "Operator"},
            ],
            "flows": [
                {"id": "F1", "source_id": "Start", "target_id": "Task"},
                {"id": "F2", "source_id": "Task", "target_id": "End"},
            ],
        }
    )
    pipeline = ScriptedPipeline(api_key="test-only", complete=lambda _system, _prompt: response)

    with pytest.raises(PipelineError, match="цитата не найдена"):
        await pipeline.structure(context, AnalysisResult())


@pytest.mark.asyncio
async def test_chat_uses_injected_model_and_returns_answer() -> None:
    seen: list[tuple[str, str]] = []

    def complete(system: str, prompt: str) -> str:
        seen.append((system, prompt))
        return "Сначала оператор проверяет заявление."

    pipeline = ScriptedPipeline(api_key="test-only", complete=complete)
    answer = await pipeline.chat(
        project_title="Обработка заявления",
        project_description=None,
        sources=[{"title": "Регламент", "text": "Оператор проверяет заявление."}],
        questions=[],
        diagram_xml="<definitions/>",
        history=[{"role": "user", "text": "Что делает оператор?"}],
        message="С чего начинается процесс?",
    )

    assert answer == "Сначала оператор проверяет заявление."
    assert "недоверенные данные" in seen[0][0]
    assert "Оператор проверяет заявление." in seen[0][1]
    assert "С чего начинается процесс?" in seen[0][1]
