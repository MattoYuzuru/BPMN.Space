import json
from datetime import UTC, datetime
from unittest.mock import patch
from urllib.error import URLError
from uuid import uuid4

import pytest

from app.domain.analysis import AnalysisResult, ContextSource, RunContext
from app.domain.models import SourceKind
from app.llm.base import PipelineError
from app.llm.deepseek import DeepSeekPipeline, _verified_quote


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
    request_body = json.loads(request.data)
    assert request_body["model"] == "deepseek-flash"
    assert request_body["thinking"] == {"type": "disabled"}
    assert request_body["max_tokens"] == 4096


def test_request_can_enable_thinking_explicitly() -> None:
    pipeline = DeepSeekPipeline(api_key="test-only", thinking_enabled=True)
    with patch("app.llm.deepseek.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            {"choices": [{"message": {"content": "{}"}}]}
        ).encode()
        pipeline._request_json("system", "prompt")
        request = urlopen.call_args.args[0]

    assert json.loads(request.data)["thinking"] == {"type": "enabled"}


def test_request_reports_timeout_separately() -> None:
    pipeline = DeepSeekPipeline(api_key="test-only", timeout_sec=17)
    with (
        patch("app.llm.deepseek.urlopen", side_effect=TimeoutError),
        pytest.raises(RuntimeError, match="не ответила за 17 секунд"),
    ):
        pipeline._request_json("system", "prompt")


def test_request_reports_network_error_separately() -> None:
    pipeline = DeepSeekPipeline(api_key="test-only")
    with (
        patch("app.llm.deepseek.urlopen", side_effect=URLError("offline")),
        pytest.raises(RuntimeError, match="связаться с сервисом модели"),
    ):
        pipeline._request_json("system", "prompt")


def test_request_reports_invalid_provider_json_separately() -> None:
    pipeline = DeepSeekPipeline(api_key="test-only")
    with patch("app.llm.deepseek.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.read.return_value = b"not-json"
        with pytest.raises(RuntimeError, match="некорректном формате"):
            pipeline._request_json("system", "prompt")


def test_request_reports_truncated_model_response_separately() -> None:
    pipeline = DeepSeekPipeline(api_key="test-only")
    with patch("app.llm.deepseek.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            {"choices": [{"message": {"content": "{}"}, "finish_reason": "length"}]}
        ).encode()
        with pytest.raises(RuntimeError, match="обрезан по лимиту длины"):
            pipeline._request_json("system", "prompt")


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
                            "quote": "Руководитель согласует заявку.",
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
    assert set(draft.trace) == {"Task_1", "Task_2"}
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
            "steps": [
                {
                    "name": "Отправить договор",
                    "lane": "Оператор",
                    "source_id": str(source_id),
                    "quote": "Цитаты в источнике нет.",
                }
            ]
        }
    )
    pipeline = DeepSeekPipeline(api_key="test-only", complete=lambda _system, _prompt: response)

    with pytest.raises(PipelineError, match="не смогла подтвердить цитатами"):
        await pipeline.structure(context, AnalysisResult())


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
