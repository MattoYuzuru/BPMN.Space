import json
from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.domain.analysis import ContextSource, RunContext
from app.domain.models import SourceKind
from app.llm.deepseek import DeepSeekPipeline


def test_request_uses_current_model_and_server_side_bearer_auth() -> None:
    payload = {"choices": [{"message": {"content": '{"steps": []}'}}]}
    pipeline = DeepSeekPipeline(api_key="test-only", model="deepseek-flash")

    with patch("app.llm.deepseek.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(payload).encode()
        response = pipeline._request_json("system", "prompt")
        request = urlopen.call_args.args[0]

    assert response == '{"steps": []}'
    assert request.full_url == "https://api.deepseek.com/chat/completions"
    assert request.get_header("Authorization") == "Bearer test-only"
    assert json.loads(request.data)["model"] == "deepseek-flash"


def test_chat_request_is_plain_text_and_receives_project_context() -> None:
    payload = {"choices": [{"message": {"content": "Уточните, кто принимает решение."}}]}
    pipeline = DeepSeekPipeline(api_key="test-only")

    with patch("app.llm.deepseek.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(payload).encode()
        response = pipeline._request_text("system", '{"user_message":"кто согласует?"}')
        request = urlopen.call_args.args[0]

    assert response == "Уточните, кто принимает решение."
    request_body = json.loads(request.data)
    assert "response_format" not in request_body
    assert request_body["messages"][1]["content"] == '{"user_message":"кто согласует?"}'


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
    responses = iter(
        [
            json.dumps(
                {
                    "new_questions": [
                        {
                            "kind": "missing_outcome",
                            "severity": "major",
                            "text": "Что происходит после согласования?",
                            "assumption": "Процесс завершается после согласования.",
                            "source_id": str(source_id),
                            "quote": "Руководитель согласует заявку.",
                        }
                    ]
                }
            ),
            json.dumps(
                {
                    "steps": [
                        {
                            "name": "Проверить комплектность документов",
                            "lane": "Оператор",
                            "source_id": str(source_id),
                            "quote": "Оператор проверяет комплектность документов.",
                        },
                        {
                            "name": "Согласовать заявку",
                            "lane": "Руководитель",
                            "source_id": str(source_id),
                            "quote": "Цитата, которой нет в источнике.",
                        },
                    ]
                }
            ),
        ]
    )
    pipeline = DeepSeekPipeline(
        api_key="test-only", complete=lambda _system, _prompt: next(responses)
    )

    analysis = await pipeline.analyze(context)
    draft = await pipeline.structure(context, analysis)

    assert len(analysis.new_questions) == 1
    assert analysis.new_questions[0].about is not None
    assert "bpmn:process" in draft.xml
    assert "Проверить комплектность документов" in draft.xml
    assert set(draft.trace) == {"Task_1"}
    assert draft.trace["Task_1"].quote == "Оператор проверяет комплектность документов."


@pytest.mark.asyncio
async def test_chat_uses_injected_model_and_returns_answer() -> None:
    seen: list[tuple[str, str]] = []

    def complete(system: str, prompt: str) -> str:
        seen.append((system, prompt))
        return "Сначала оператор проверяет заявление."

    pipeline = DeepSeekPipeline(api_key="test-only", complete=complete)
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
