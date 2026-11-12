"""Протокол Responses у совместимого провайдера (ADR-0013): форма запроса, ответ, согласование.

Транспорт без сети: ответы повторяют форму живого шлюза подписки (OpenAI Buffet) и OpenAI.
"""

import json
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.llm.base import OutputTruncatedError, track_usage
from app.llm.capabilities import capabilities_for, forget_all, remember
from app.llm.client import WIRE_RESPONSES, LlmConfig, LlmRefusalError, RetryPolicy
from app.llm.factory import build_client
from app.llm.multimodal import document_attachment, image_attachment
from app.llm.openai_compatible import RESPONSES_ONLY_MESSAGE, OpenAICompatibleClient
from app.llm.openai_responses import (
    OpenAIResponsesClient,
    catalog_capabilities,
    unsupported_params,
)
from app.llm.tools import ConversationMessage, ToolDefinition, ToolUse
from tests.llm_helpers import json_transport, no_sleep

SECRET = "sk-buffet-test-SECRET-0123456789"  # noqa: S105
BASE = "https://buffet.example.test/v1"


@pytest.fixture(autouse=True)
def _clean_registry() -> Iterator[None]:
    forget_all()
    yield
    forget_all()


def _config(**kw: Any) -> LlmConfig:
    values: dict[str, Any] = {
        "provider": "openai_compatible",
        "model": "gpt-6.1-sol",
        "api_key": SecretStr(SECRET),
        "base_url": BASE,
        "wire_api": WIRE_RESPONSES,
    }
    values.update(kw)
    return LlmConfig(**values)


def _client(
    handler: Callable[[httpx.Request], httpx.Response],
    requests: list[httpx.Request] | None = None,
    **kw: Any,
) -> OpenAIResponsesClient:
    return OpenAIResponsesClient(
        _config(**kw),
        policy=RetryPolicy(max_retries=2, sleep=no_sleep, jitter=lambda: 0.0),
        transport=json_transport(handler, requests),
    )


def _response(*output: dict[str, Any], status: str = "completed", **extra: Any) -> httpx.Response:
    body: dict[str, Any] = {
        "id": "resp_1",
        "object": "response",
        "status": status,
        "output": list(output),
        "usage": {
            "input_tokens": 120,
            "input_tokens_details": {"cached_tokens": 20, "cache_write_tokens": 0},
            "output_tokens": 16,
        },
        **extra,
    }
    return httpx.Response(200, json=body)


def _text(text: str) -> dict[str, Any]:
    return {
        "type": "message",
        "id": "msg_1",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def _body(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.content)


# ---------- форма запроса ----------


async def test_json_request_is_stateless_responses_with_instructions_and_format() -> None:
    requests: list[httpx.Request] = []
    client = _client(lambda _r: _response(_text('{"ok":true}')), requests)
    assert await client.complete("sys", "user", json_mode=True, max_tokens=777) == '{"ok":true}'
    request = requests[0]
    body = _body(request)
    assert str(request.url) == f"{BASE}/responses"
    assert request.headers["Authorization"] == f"Bearer {SECRET}"
    assert body["model"] == "gpt-6.1-sol"
    assert body["instructions"] == "sys"
    assert body["input"] == [{"role": "user", "content": "user"}]
    assert body["store"] is False
    assert body["stream"] is False
    assert body["max_output_tokens"] == 777
    assert body["text"] == {"format": {"type": "json_object"}}
    # Модель неизвестна: температура 0 отправляется, пока сервер от неё не откажется.
    assert body["temperature"] == 0.0
    assert "reasoning" not in body
    assert "messages" not in body


async def test_text_request_has_no_json_format_and_caps_chat_tokens() -> None:
    requests: list[httpx.Request] = []
    client = _client(lambda _r: _response(_text("привет")), requests)
    assert await client.complete("s", "u", json_mode=False, max_tokens=16_384) == "привет"
    body = _body(requests[0])
    assert "text" not in body
    assert "temperature" not in body
    assert body["max_output_tokens"] == 4096


async def test_usage_counts_input_output_and_cached_tokens() -> None:
    client = _client(lambda _r: _response(_text("{}")))
    with track_usage() as usage:
        await client.complete("s", "u", json_mode=True, max_tokens=10)
    assert (usage.tokens_in, usage.tokens_out, usage.cache_read_tokens) == (120, 16, 20)
    assert usage.requests == 1


async def test_message_parts_are_joined_and_reasoning_items_are_skipped() -> None:
    reasoning = {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "x"}
    message = _text('{"a":')
    message["content"].append({"type": "output_text", "text": "1}"})
    client = _client(lambda _r: _response(reasoning, message))
    assert await client.complete("s", "u", json_mode=True, max_tokens=10) == '{"a":1}'


# ---------- статус ответа ----------


async def test_incomplete_by_length_is_truncation_not_a_partial_result() -> None:
    client = _client(
        lambda _r: _response(
            _text('{"a":'),
            status="incomplete",
            incomplete_details={"reason": "max_output_tokens"},
        )
    )
    with pytest.raises(OutputTruncatedError):
        await client.complete("s", "u", json_mode=True, max_tokens=10)


async def test_content_filter_and_refusal_part_are_refusals() -> None:
    filtered = _client(
        lambda _r: _response(status="incomplete", incomplete_details={"reason": "content_filter"})
    )
    with pytest.raises(LlmRefusalError):
        await filtered.complete("s", "u", json_mode=True, max_tokens=10)
    refusal = {
        "type": "message",
        "role": "assistant",
        "content": [{"type": "refusal", "refusal": "Не могу помочь"}],
    }
    refused = _client(lambda _r: _response(refusal))
    with pytest.raises(LlmRefusalError):
        await refused.complete("s", "u", json_mode=True, max_tokens=10)


async def test_failed_status_and_broken_shape_are_errors() -> None:
    failed = _client(lambda _r: _response(status="failed", error={"code": "server_error"}))
    with pytest.raises(RuntimeError, match="не завершила"):
        await failed.complete("s", "u", json_mode=True, max_tokens=10)
    broken = _client(lambda _r: httpx.Response(200, json={"status": "completed"}))
    with pytest.raises(RuntimeError, match="неизвестной структуры"):
        await broken.complete("s", "u", json_mode=True, max_tokens=10)
    empty = _client(lambda _r: _response())
    with pytest.raises(RuntimeError, match="пустой"):
        await empty.complete("s", "u", json_mode=True, max_tokens=10)


# ---------- согласование необязательных параметров ----------


def _gateway_rejects(*names: str) -> Callable[[httpx.Request], httpx.Response]:
    """Шлюз подписки отвергает лимит ответа и температуру одним сообщением."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = _body(request)
        present = [name for name in names if name in body]
        if present:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "message": "Unsupported by ChatGPT plan route: " + ", ".join(present),
                        "type": "gateway_error",
                        "code": "unsupported_parameter",
                    }
                },
            )
        return _response(_text("{}"))

    return handler


async def test_rejected_optional_params_are_dropped_once_for_the_client() -> None:
    requests: list[httpx.Request] = []
    client = _client(_gateway_rejects("max_output_tokens", "temperature"), requests)
    assert await client.complete("s", "u", json_mode=True, max_tokens=10) == "{}"
    assert len(requests) == 2
    retried = _body(requests[1])
    assert "max_output_tokens" not in retried
    assert "temperature" not in retried
    assert retried["text"] == {"format": {"type": "json_object"}}
    # Следующий вызов того же клиента сразу идёт без отвергнутых параметров.
    await client.complete("s", "u", json_mode=True, max_tokens=10)
    assert len(requests) == 3


async def test_openai_style_param_error_drops_reasoning() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "reasoning" in _body(request):
            return httpx.Response(
                400,
                json={
                    "error": {
                        "message": "Unsupported parameter: 'reasoning.effort' is not supported.",
                        "param": "reasoning.effort",
                        "code": "unsupported_parameter",
                    }
                },
            )
        return _response(_text("ok"))

    client = _client(handler, requests)
    _remember_catalog(client)
    assert await client.complete("s", "u", json_mode=False, max_tokens=10, effort="high") == "ok"
    assert _body(requests[0])["reasoning"] == {"effort": "high"}
    assert "reasoning" not in _body(requests[1])


async def test_other_bad_requests_are_not_retried_or_worked_around() -> None:
    requests: list[httpx.Request] = []
    client = _client(
        lambda _r: httpx.Response(400, json={"error": {"message": "Invalid input"}}), requests
    )
    with pytest.raises(RuntimeError, match="HTTP 400"):
        await client.complete("s", "u", json_mode=True, max_tokens=10)
    assert len(requests) == 1
    # Отказ от обязательного поля не обходится: снимать нечего.
    required = _client(
        lambda _r: httpx.Response(
            400, json={"error": {"code": "unsupported_parameter", "param": "input"}}
        )
    )
    with pytest.raises(RuntimeError, match="HTTP 400"):
        await required.complete("s", "u", json_mode=True, max_tokens=10)


async def test_context_overflow_is_recognised_on_responses() -> None:
    client = _client(
        lambda _r: httpx.Response(
            400,
            json={
                "error": {
                    "message": "Your input exceeds the context window of this model.",
                    "code": "context_length_exceeded",
                }
            },
        )
    )
    with pytest.raises(Exception, match="окно") as error:
        await client.complete("s", "u", json_mode=True, max_tokens=10)
    assert type(error.value).__name__ == "ContextOverflowError"


def test_unsupported_params_need_an_explicit_refusal() -> None:
    assert unsupported_params(
        '{"error":{"message":"Unsupported by ChatGPT plan route: max_output_tokens, temperature",'
        '"code":"unsupported_parameter"}}'
    ) == {"max_output_tokens", "temperature"}
    assert unsupported_params(
        '{"error":{"param":"reasoning.effort","code":"unsupported_parameter"}}'
    ) == {"reasoning"}
    # Упоминание без отказа и неизвестные поля не считаются.
    assert unsupported_params('{"error":{"message":"temperature must be 1"}}') == set()
    assert unsupported_params('{"error":{"code":"unsupported_parameter","param":"input"}}') == set()
    assert unsupported_params("not json, but unsupported: temperature") == {"temperature"}
    assert unsupported_params('{"error":{"message":"Unsupported: text.temperature_x"}}') == set()


# ---------- протокол не тот ----------


async def test_responses_client_names_the_other_protocol_on_404_or_501() -> None:
    client = _client(lambda _r: httpx.Response(404, json={"error": {"message": "Not found"}}))
    with pytest.raises(RuntimeError, match="Chat Completions"):
        await client.complete("s", "u", json_mode=True, max_tokens=10)


async def test_chat_client_points_to_responses_when_gateway_asks_for_it() -> None:
    chat = OpenAICompatibleClient(
        _config(wire_api=None),
        policy=RetryPolicy(max_retries=0, sleep=no_sleep),
        transport=json_transport(
            lambda _r: httpx.Response(
                501,
                json={
                    "error": {
                        "message": "Use POST /v1/responses. This gateway exposes the "
                        "subscription Responses API",
                        "code": "use_responses_api",
                    }
                },
            )
        ),
    )
    with pytest.raises(RuntimeError) as error:
        await chat.complete("s", "u", json_mode=True, max_tokens=10)
    assert str(error.value) == RESPONSES_ONLY_MESSAGE


def test_factory_builds_the_client_for_the_wire_protocol() -> None:
    assert isinstance(build_client(_config()), OpenAIResponsesClient)
    chat = build_client(_config(wire_api="chat_completions"))
    assert type(chat) is OpenAICompatibleClient
    assert type(build_client(_config(wire_api=None))) is OpenAICompatibleClient


async def test_user_supplied_responses_url_is_guarded_like_chat() -> None:
    client = build_client(
        _config(base_url="https://169.254.169.254/v1"),
        user_supplied_url=True,
        transport=json_transport(lambda _r: _response(_text("{}"))),
    )
    with pytest.raises(RuntimeError, match="закрытую сеть"):
        await client.complete("s", "u", json_mode=True, max_tokens=1)


# ---------- каталог моделей ----------


_CATALOG = {
    "object": "list",
    "data": [
        {
            "id": "gpt-6.1-sol",
            "slug": "gpt-6.1-sol",
            "display_name": "GPT-6.1 Sol",
            "context_window": 500_000,
            "supported_reasoning_levels": [
                {"effort": "low"},
                {"effort": "medium"},
                {"effort": "high"},
                {"effort": "xhigh"},
                {"effort": "max"},
            ],
            "default_reasoning_level": "low",
            "input_modalities": ["text", "image"],
        },
        {"id": "plain-model"},
    ],
}


def _remember_catalog(client: OpenAIResponsesClient) -> None:
    """Каталог, как его отдал бы `/models`: без сетевого запроса (для тестов уровня)."""
    item = _CATALOG["data"][0]
    base = capabilities_for("openai_compatible", "gpt-6.1-sol", base_url=BASE)
    remember("openai_compatible", "gpt-6.1-sol", catalog_capabilities(item, base), base_url=BASE)
    assert client.capabilities().effort_levels


async def test_models_describe_window_effort_and_vision_scoped_by_host() -> None:
    requests: list[httpx.Request] = []
    client = _client(lambda _r: httpx.Response(200, json=_CATALOG), requests)
    models = await client.list_models()
    assert [item.id for item in models] == ["gpt-6.1-sol", "plain-model"]
    assert str(requests[0].url) == f"{BASE}/models"
    sol = models[0]
    assert sol.label == "GPT-6.1 Sol"
    caps = sol.capabilities
    assert caps is not None
    assert caps.context_tokens == 500_000
    assert caps.effort_levels == ("low", "medium", "high", "xhigh", "max")
    assert caps.effort_default == "low"
    assert caps.vision is True
    assert caps.accepts_temperature is False
    assert models[1].capabilities is None
    # Пайплайн видит описание того же сервера, а одноимённая модель другого хоста — нет.
    assert capabilities_for("openai_compatible", "gpt-6.1-sol", base_url=BASE).known
    other = capabilities_for("openai_compatible", "gpt-6.1-sol", base_url="https://other.test/v1")
    assert not other.known
    assert not capabilities_for("openai", "gpt-6.1-sol").known


async def test_known_reasoning_model_gets_effort_and_no_temperature() -> None:
    requests: list[httpx.Request] = []
    client = _client(lambda _r: _response(_text("{}")), requests)
    _remember_catalog(client)
    await client.complete("s", "u", json_mode=True, max_tokens=10, effort="xhigh")
    body = _body(requests[0])
    assert body["reasoning"] == {"effort": "xhigh"}
    assert "temperature" not in body


# ---------- изображения и PDF ----------


async def test_vision_and_pdf_use_input_parts() -> None:
    requests: list[httpx.Request] = []
    client = _client(lambda _r: _response(_text("{}")), requests)
    image = image_attachment(b"\x89PNG", mime="image/png")
    await client.complete_vision("s", "смотри", images=[image], json_mode=True, max_tokens=10)
    content = _body(requests[0])["input"][0]["content"]
    assert content[0] == {"type": "input_text", "text": "смотри"}
    assert content[1]["type"] == "input_image"
    assert content[1]["image_url"].startswith("data:image/png;base64,")
    with pytest.raises(Exception, match="PDF"):
        await client.complete_document(
            "s", "u", document=document_attachment(b"%PDF"), json_mode=True, max_tokens=10
        )


# ---------- инструменты ----------


def _tools() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name="read_source",
            description="Прочитать источник",
            input_schema={"type": "object", "properties": {"id": {"type": "string"}}},
        )
    ]


async def test_tool_turn_parses_calls_and_keeps_encrypted_reasoning() -> None:
    requests: list[httpx.Request] = []
    reasoning = {
        "type": "reasoning",
        "id": "rs_1",
        "summary": [],
        "encrypted_content": "opaque+/==",
        "status": "completed",
    }
    call = {
        "type": "function_call",
        "id": "fc_1",
        "call_id": "call_1",
        "name": "read_source",
        "arguments": '{"id":"s1"}',
        "status": "completed",
    }
    client = _client(lambda _r: _response(reasoning, call), requests)
    messages = [ConversationMessage(role="user", text="Собери схему")]
    turn = await client.complete_with_tools("sys", messages, _tools(), max_tokens=100)
    assert turn.tool_uses == (ToolUse(id="call_1", name="read_source", arguments='{"id":"s1"}'),)
    assert turn.text is None
    assert turn.stop_reason == "tool_calls"
    assert turn.provider_blocks == (
        {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "opaque+/=="},
    )
    body = _body(requests[0])
    assert body["tools"] == [
        {
            "type": "function",
            "name": "read_source",
            "description": "Прочитать источник",
            "parameters": {"type": "object", "properties": {"id": {"type": "string"}}},
            "strict": False,
        }
    ]
    assert body["include"] == ["reasoning.encrypted_content"]
    assert body["instructions"] == "sys"
    assert "text" not in body


async def test_tool_history_replays_reasoning_calls_and_outputs_in_order() -> None:
    requests: list[httpx.Request] = []
    client = _client(lambda _r: _response(_text("Готово")), requests)
    reasoning = {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "e"}
    history = [
        ConversationMessage(role="user", text="Собери схему"),
        ConversationMessage(
            role="assistant",
            text="Читаю",
            tool_uses=(ToolUse(id="call_1", name="read_source", arguments='{"id":"s1"}'),),
            provider_blocks=(
                reasoning,
                # Чужие блоки (thinking Anthropic) и рассуждение без шифртекста не повторяются.
                {"type": "thinking", "thinking": "…", "signature": "sig"},
                {"type": "reasoning", "id": "rs_2", "summary": []},
            ),
        ),
        ConversationMessage(role="tool", text="Текст источника", tool_use_id="call_1"),
    ]
    turn = await client.complete_with_tools("sys", history, _tools(), max_tokens=100)
    assert turn.text == "Готово"
    assert turn.tool_uses == ()
    assert _body(requests[0])["input"] == [
        {"role": "user", "content": "Собери схему"},
        reasoning,
        {"role": "assistant", "content": "Читаю"},
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "read_source",
            "arguments": '{"id":"s1"}',
        },
        {"type": "function_call_output", "call_id": "call_1", "output": "Текст источника"},
    ]


async def test_tool_turn_without_text_or_calls_is_an_error() -> None:
    client = _client(lambda _r: _response())
    messages = [ConversationMessage(role="user", text="?")]
    with pytest.raises(RuntimeError, match="без запросов инструментов"):
        await client.complete_with_tools("s", messages, _tools(), max_tokens=10)
    with pytest.raises(ValueError, match="инструмента"):
        await client.complete_with_tools("s", messages, [], max_tokens=10)
