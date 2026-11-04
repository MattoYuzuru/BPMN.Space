"""Адаптеры провайдеров: форма запросов, повторы, ошибки и защита ключа. Сети нет."""

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx
import httpx2
import pytest
from pydantic import SecretStr

from app.llm.anthropic import AnthropicClient
from app.llm.base import OutputTruncatedError, PipelineError, run_deadline, track_usage
from app.llm.client import (
    LlmAuthError,
    LlmConfig,
    LlmRefusalError,
    RetryPolicy,
    redact_secrets,
)
from app.llm.openai import OpenAIClient
from app.llm.openai_compatible import OpenAICompatibleClient
from tests.llm_helpers import json_transport, no_sleep, ok_chat

SECRET = "sk-test-SECRET-0123456789abcdef"  # noqa: S105


def _config(**kw: Any) -> LlmConfig:
    values: dict[str, Any] = {
        "provider": "openai_compatible",
        "model": "deepseek-chat",
        "api_key": SecretStr(SECRET),
        "base_url": "https://llm.example.test/v1",
    }
    values.update(kw)
    return LlmConfig(**values)


def _compat(handler, requests=None, *, retries: int = 3, **kw: Any) -> OpenAICompatibleClient:
    sleeps: list[float] = []
    client = OpenAICompatibleClient(
        _config(**kw),
        policy=RetryPolicy(
            max_retries=retries,
            sleep=lambda s: _record(sleeps, s),
            jitter=lambda: 0.0,
        ),
        transport=json_transport(handler, requests),
    )
    client.sleeps = sleeps  # type: ignore[attr-defined]
    return client


async def _record(sleeps: list[float], seconds: float) -> None:
    sleeps.append(seconds)


# ---------- openai_compatible ----------


async def test_compatible_request_uses_model_bearer_and_json_mode() -> None:
    requests: list[httpx.Request] = []
    client = _compat(lambda _r: ok_chat("{}"), requests)
    assert await client.complete("sys", "user", json_mode=True, max_tokens=777) == "{}"
    request = requests[0]
    body = json.loads(request.content)
    assert str(request.url) == "https://llm.example.test/v1/chat/completions"
    assert request.headers["Authorization"] == f"Bearer {SECRET}"
    assert body["model"] == "deepseek-chat"
    assert body["max_tokens"] == 777
    assert body["response_format"] == {"type": "json_object"}
    assert body["temperature"] == 0.0
    assert "thinking" not in body


async def test_compatible_text_request_has_no_json_mode_or_temperature_and_caps_tokens() -> None:
    requests: list[httpx.Request] = []
    client = _compat(lambda _r: ok_chat("привет"), requests)
    assert await client.complete("s", "u", json_mode=False, max_tokens=16_384) == "привет"
    body = json.loads(requests[0].content)
    assert "response_format" not in body
    assert "temperature" not in body
    assert body["max_tokens"] == 4096


async def test_compatible_deepseek_thinking_and_disabled_json_mode() -> None:
    requests: list[httpx.Request] = []
    client = _compat(lambda _r: ok_chat("{}"), requests, thinking=False, json_mode=False)
    await client.complete("s", "u", json_mode=True, max_tokens=10)
    body = json.loads(requests[0].content)
    assert body["thinking"] == {"type": "disabled"}
    assert "response_format" not in body


async def test_retry_after_is_respected_then_success() -> None:
    answers = iter([httpx.Response(429, headers={"Retry-After": "7"}), ok_chat("{}")])
    client = _compat(lambda _r: next(answers))
    assert await client.complete("s", "u", json_mode=True, max_tokens=1) == "{}"
    assert client.sleeps == [7.0]  # type: ignore[attr-defined]


@pytest.mark.parametrize("code", [408, 429, 500, 502, 503, 504, 529])
async def test_transient_http_errors_are_retried_with_bound(code: int) -> None:
    calls = 0

    def handler(_r: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(code)

    client = _compat(handler, retries=2)
    with pytest.raises(RuntimeError, match=f"HTTP {code}"):
        await client.complete("s", "u", json_mode=True, max_tokens=1)
    assert calls == 3
    assert client.sleeps == [0.5, 1.0]  # type: ignore[attr-defined]


@pytest.mark.parametrize("code", [400, 402, 404, 422])
async def test_client_errors_are_not_retried(code: int) -> None:
    calls = 0

    def handler(_r: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(code, text=f"echo {SECRET}")

    client = _compat(handler)
    with pytest.raises(RuntimeError, match=f"HTTP {code}") as info:
        await client.complete("s", "u", json_mode=True, max_tokens=1)
    assert calls == 1
    assert SECRET not in str(info.value)


@pytest.mark.parametrize("code", [401, 403])
async def test_auth_errors_name_the_key_problem_without_leaking_it(code: int) -> None:
    client = _compat(lambda _r: httpx.Response(code, text=f"bad key {SECRET}"))
    with pytest.raises(LlmAuthError) as info:
        await client.complete("s", "u", json_mode=True, max_tokens=1)
    assert "ключ" in str(info.value)
    assert SECRET not in str(info.value)


def test_backoff_is_bounded_and_jittered() -> None:
    low = RetryPolicy(base_sec=1, max_sec=10, jitter=lambda: 0.0)
    high = RetryPolicy(base_sec=1, max_sec=10, jitter=lambda: 1.0)
    assert [low.delay(n, None) for n in range(6)] == [0.5, 1.0, 2.0, 4.0, 5.0, 5.0]
    assert [high.delay(n, None) for n in range(6)] == [1.0, 2.0, 4.0, 8.0, 10.0, 10.0]
    assert high.delay(0, 1000.0) == 30.0  # Retry-After тоже ограничен


async def test_retry_after_with_a_date_is_ignored() -> None:
    answers = iter(
        [httpx.Response(503, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}), ok_chat()]
    )
    client = _compat(lambda _r: next(answers))
    await client.complete("s", "u", json_mode=True, max_tokens=1)
    assert client.sleeps == [0.5]  # type: ignore[attr-defined]


async def test_read_timeout_is_retried_at_most_once() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("slow", request=request)

    client = _compat(handler, timeout_sec=17)
    with pytest.raises(RuntimeError, match="не ответила за 17 секунд"):
        await client.complete("s", "u", json_mode=True, max_tokens=1)
    assert calls == 2


async def test_network_errors_keep_full_retries() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("refused", request=request)

    client = _compat(handler, retries=3)
    with pytest.raises(RuntimeError, match="связаться с сервисом модели"):
        await client.complete("s", "u", json_mode=True, max_tokens=1)
    assert calls == 4


async def test_usage_is_recorded_and_broken_usage_is_ignored() -> None:
    body = {
        "choices": [{"message": {"content": "{}"}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 25},
    }
    client = _compat(lambda _r: httpx.Response(200, json=body))
    with track_usage() as usage:
        await client.complete("s", "u", json_mode=True, max_tokens=1)
        await client.complete("s", "u", json_mode=True, max_tokens=1)
    assert (usage.tokens_in, usage.tokens_out, usage.requests) == (200, 50, 2)
    broken = {"choices": [{"message": {"content": "{}"}}], "usage": {"prompt_tokens": "много"}}
    other = _compat(lambda _r: httpx.Response(200, json=broken))
    with track_usage() as usage2:
        await other.complete("s", "u", json_mode=True, max_tokens=1)
    assert (usage2.tokens_in, usage2.tokens_out) == (0, 0)


async def test_compatible_usage_reads_cached_tokens_and_count_tokens_estimates() -> None:
    body = {
        "choices": [{"message": {"content": "{}"}}],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 25,
            "prompt_tokens_details": {"cached_tokens": 60},
        },
    }
    client = _compat(lambda _r: httpx.Response(200, json=body))
    with track_usage() as usage:
        await client.complete("s", "u", json_mode=True, max_tokens=1)
    assert (usage.tokens_in, usage.tokens_out) == (100, 25)
    assert (usage.cache_read_tokens, usage.cache_write_tokens) == (60, 0)
    # Chat Completions не умеет считать токены: оценка по знакам и chars_per_token.
    approx = await client.count_tokens("12345", "67890")
    assert approx == 5


async def test_anthropic_count_tokens_is_exact_and_survives_provider_error() -> None:
    sdk = _Sdk(count=123)
    client = _anthropic(sdk)
    assert await client.count_tokens("СИСТЕМА", "запрос") == 123
    assert sdk.count_calls[0]["model"] == "claude-opus-5-5"
    failing = _Sdk(count=anthropic.APIConnectionError(request=httpx2.Request("POST", "https://x")))
    assert await _anthropic(failing).count_tokens("sys", "user") > 0


async def test_response_shape_errors_are_reported_separately() -> None:
    bad = _compat(lambda _r: httpx.Response(200, content=b"not-json"))
    with pytest.raises(RuntimeError, match="некорректном формате"):
        await bad.complete("s", "u", json_mode=True, max_tokens=1)
    cut = _compat(
        lambda _r: httpx.Response(
            200, json={"choices": [{"message": {"content": "{}"}, "finish_reason": "length"}]}
        )
    )
    with pytest.raises(OutputTruncatedError, match="обрезан по лимиту длины"):
        await cut.complete("s", "u", json_mode=True, max_tokens=1)
    refused = _compat(
        lambda _r: httpx.Response(
            200, json={"choices": [{"message": {"content": None, "refusal": "no"}}]}
        )
    )
    with pytest.raises(LlmRefusalError):
        await refused.complete("s", "u", json_mode=True, max_tokens=1)


async def test_retry_is_skipped_when_run_deadline_would_pass() -> None:
    calls = 0

    def handler(_r: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    client = _compat(handler)
    client._policy.jitter = lambda: 1.0
    with run_deadline(0.5), pytest.raises(RuntimeError, match="HTTP 503"):
        await client.complete("s", "u", json_mode=True, max_tokens=1)
    assert calls == 1
    assert client.sleeps == []  # type: ignore[attr-defined]


async def test_request_timeout_is_cut_to_the_run_deadline() -> None:
    seen: list[float | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.extensions["timeout"]["read"])
        return ok_chat()

    client = _compat(handler, timeout_sec=120)
    with run_deadline(5):
        await client.complete("s", "u", json_mode=True, max_tokens=1)
    assert seen[0] is not None
    assert seen[0] <= 5
    with run_deadline(1e-9):
        await _sleep_a_bit()
        with pytest.raises(PipelineError, match="не уложился"):
            await client.complete("s", "u", json_mode=True, max_tokens=1)


async def _sleep_a_bit() -> None:
    await asyncio.sleep(0.001)


async def test_list_models_reads_data_ids() -> None:
    requests: list[httpx.Request] = []
    client = _compat(
        lambda _r: httpx.Response(200, json={"data": [{"id": "b"}, {"id": "a"}]}), requests
    )
    assert [item.id for item in await client.list_models()] == ["a", "b"]
    assert requests[0].method == "GET"
    assert str(requests[0].url) == "https://llm.example.test/v1/models"


async def test_user_supplied_url_is_checked_before_every_request() -> None:
    client = OpenAICompatibleClient(
        _config(base_url="https://169.254.169.254/v1"),
        guard_host=True,
        transport=json_transport(lambda _r: ok_chat()),
    )
    with pytest.raises(RuntimeError, match="закрытую сеть"):
        await client.complete("s", "u", json_mode=True, max_tokens=1)


def test_user_supplied_http_url_is_refused_unless_host_is_allowed() -> None:
    with pytest.raises(ValueError, match="https"):
        OpenAICompatibleClient(
            _config(base_url="http://models.internal/v1"),
            guard_host=True,
        )
    OpenAICompatibleClient(
        _config(base_url="http://models.internal/v1"),
        guard_host=True,
        allowed_private_hosts=("models.internal",),
    )


# ---------- openai ----------


async def test_openai_uses_max_completion_tokens_and_fixed_url() -> None:
    requests: list[httpx.Request] = []
    client = OpenAIClient(
        _config(provider="openai", model="gpt-5", base_url="https://evil.example/v1"),
        transport=json_transport(lambda _r: ok_chat("{}"), requests),
    )
    await client.complete("s", "u", json_mode=True, max_tokens=999)
    body = json.loads(requests[0].content)
    assert str(requests[0].url) == "https://api.openai.com/v1/chat/completions"
    assert body["max_completion_tokens"] == 999
    assert "max_tokens" not in body
    assert "temperature" not in body  # рассуждающие модели принимают только значение по умолчанию
    assert body["response_format"] == {"type": "json_object"}


async def test_openai_classic_model_keeps_zero_temperature() -> None:
    requests: list[httpx.Request] = []
    client = OpenAIClient(
        _config(provider="openai", model="gpt-4o"),
        transport=json_transport(lambda _r: ok_chat("{}"), requests),
    )
    await client.complete("s", "u", json_mode=True, max_tokens=5)
    assert json.loads(requests[0].content)["temperature"] == 0.0


async def test_openai_model_list_keeps_chat_models_only() -> None:
    payload = {"data": [{"id": n} for n in ["gpt-4o", "text-embedding-3", "whisper-1", "o3", "x"]]}
    client = OpenAIClient(
        _config(provider="openai"),
        transport=json_transport(lambda _r: httpx.Response(200, json=payload)),
    )
    assert [item.id for item in await client.list_models()] == ["gpt-4o", "o3"]


# ---------- anthropic ----------


class _Stream:
    def __init__(self, message: Any) -> None:
        self._message = message

    async def __aenter__(self) -> "_Stream":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def get_final_message(self) -> Any:
        if isinstance(self._message, Exception):
            raise self._message
        return self._message


class _Sdk:
    def __init__(self, *messages: Any, count: int | Exception = 42) -> None:
        self.calls: list[dict[str, Any]] = []
        self.count_calls: list[dict[str, Any]] = []
        self._count = count
        self._messages = list(messages)
        self.messages = SimpleNamespace(stream=self._stream, count_tokens=self._count_tokens)

    def _stream(self, **kwargs: Any) -> _Stream:
        self.calls.append(kwargs)
        return _Stream(self._messages.pop(0))

    async def _count_tokens(self, **kwargs: Any) -> Any:
        self.count_calls.append(kwargs)
        if isinstance(self._count, Exception):
            raise self._count
        return SimpleNamespace(input_tokens=self._count)

    async def close(self) -> None:
        return None


def _message(text: str = "{}", stop: str = "end_turn", **usage: int) -> Any:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop,
        usage=SimpleNamespace(
            **{
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
                **usage,
            }
        ),
    )


def _anthropic(sdk: _Sdk, **kw: Any) -> AnthropicClient:
    return AnthropicClient(
        _config(provider="anthropic", model="claude-opus-5-5", base_url=None, **kw),
        policy=RetryPolicy(max_retries=2, sleep=no_sleep, jitter=lambda: 0.0),
        sdk=sdk,  # type: ignore[arg-type]
    )


def _status_error(cls: type[anthropic.APIStatusError], code: int, **headers: str) -> Any:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls(
        "x",
        response=httpx.Response(code, headers=headers, request=request),  # type: ignore[arg-type]
        body=None,
    )


async def test_anthropic_request_omits_forbidden_sampling_and_thinking() -> None:
    sdk = _Sdk(_message("{}"))
    client = _anthropic(sdk, effort="high")
    assert await client.complete("СИСТЕМА", "user", json_mode=True, max_tokens=60_000) == "{}"
    call = sdk.calls[0]
    assert not {"temperature", "top_p", "top_k", "thinking"} & call.keys()
    assert call["model"] == "claude-opus-5-5"
    assert call["max_tokens"] == 60_000
    assert call["output_config"] == {"effort": "high"}
    assert call["cache_control"] == {"type": "ephemeral"}
    assert call["messages"] == [{"role": "user", "content": "user"}]  # без prefill ассистента
    system = call["system"][0]["text"]
    assert system.startswith("СИСТЕМА")
    assert "JSON" in system


async def test_anthropic_chat_is_plain_and_old_haiku_has_no_effort() -> None:
    sdk = _Sdk(_message("привет"))
    client = AnthropicClient(
        _config(provider="anthropic", model="claude-haiku-4-5", base_url=None),
        sdk=sdk,  # type: ignore[arg-type]
    )
    await client.complete("S", "u", json_mode=False, max_tokens=16_000)
    call = sdk.calls[0]
    assert call["max_tokens"] == 4096
    assert "output_config" not in call
    assert call["system"][0]["text"] == "S"


async def test_anthropic_effort_per_request_over_server_and_model_defaults() -> None:
    """Профиль прогона → явный LLM_ANTHROPIC_EFFORT → умолчание модели из каталога."""
    sdk = _Sdk(_message("{}"), _message("{}"), _message("{}"), _message("{}"))
    haiku = AnthropicClient(
        _config(provider="anthropic", model="claude-haiku-5-5", base_url=None, effort=None),
        sdk=sdk,  # type: ignore[arg-type]
    )
    await haiku.complete("S", "u", json_mode=True, max_tokens=128_000)
    await haiku.complete("S", "u", json_mode=True, max_tokens=128_000, effort="max")
    sonnet = AnthropicClient(
        _config(provider="anthropic", model="claude-sonnet-5-5", base_url=None, effort=None),
        sdk=sdk,  # type: ignore[arg-type]
    )
    await sonnet.complete("S", "u", json_mode=True, max_tokens=128_000)
    server = AnthropicClient(
        _config(provider="anthropic", model="claude-sonnet-5-5", base_url=None, effort="low"),
        sdk=sdk,  # type: ignore[arg-type]
    )
    await server.complete("S", "u", json_mode=True, max_tokens=128_000, effort="xhigh")
    efforts = [call["output_config"]["effort"] for call in sdk.calls]
    assert efforts == ["medium", "max", "high", "xhigh"]
    assert sdk.calls[0]["max_tokens"] == 128_000


async def test_anthropic_usage_counts_cache_and_stop_reasons() -> None:
    sdk = _Sdk(
        _message(cache_read_input_tokens=100, cache_creation_input_tokens=20),
        _message(stop="max_tokens"),
        _message(stop="refusal"),
        _message(text="  "),
    )
    client = _anthropic(sdk)
    with track_usage() as usage:
        await client.complete("s", "u", json_mode=True, max_tokens=1)
    assert (usage.tokens_in, usage.tokens_out) == (130, 5)
    assert (usage.cache_read_tokens, usage.cache_write_tokens) == (100, 20)
    with pytest.raises(OutputTruncatedError):
        await client.complete("s", "u", json_mode=True, max_tokens=1)
    with pytest.raises(LlmRefusalError):
        await client.complete("s", "u", json_mode=True, max_tokens=1)
    with pytest.raises(RuntimeError, match="пустой"):
        await client.complete("s", "u", json_mode=True, max_tokens=1)


async def test_anthropic_typed_errors_map_to_retry_and_auth_semantics() -> None:
    sdk = _Sdk(
        _status_error(anthropic.RateLimitError, 429, **{"retry-after": "3"}),
        anthropic.APITimeoutError(request=httpx.Request("POST", "https://x")),  # type: ignore[arg-type]
        _message("{}"),
    )
    client = _anthropic(sdk)
    assert await client.complete("s", "u", json_mode=True, max_tokens=1) == "{}"
    assert len(sdk.calls) == 3

    auth = _anthropic(_Sdk(_status_error(anthropic.AuthenticationError, 401)))
    with pytest.raises(LlmAuthError):
        await auth.complete("s", "u", json_mode=True, max_tokens=1)

    sdk5 = _Sdk(*[_status_error(anthropic.InternalServerError, 500) for _ in range(3)])
    with pytest.raises(RuntimeError, match="HTTP 500"):
        await _anthropic(sdk5).complete("s", "u", json_mode=True, max_tokens=1)
    assert len(sdk5.calls) == 3  # SDK сам не повторяет: повторы только наши

    bad = _anthropic(_Sdk(_status_error(anthropic.BadRequestError, 400)))
    with pytest.raises(RuntimeError, match="HTTP 400"):
        await bad.complete("s", "u", json_mode=True, max_tokens=1)

    conn = _anthropic(
        _Sdk(
            *[
                anthropic.APIConnectionError(
                    request=httpx.Request("POST", "https://x")  # type: ignore[arg-type]
                )
            ]
            * 3
        )
    )
    with pytest.raises(RuntimeError, match="связаться"):
        await conn.complete("s", "u", json_mode=True, max_tokens=1)


async def test_anthropic_models_use_x_api_key_over_the_real_sdk_transport() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(
            200,
            json={
                "data": [
                    {
                        "id": "claude-opus-5-5",
                        "display_name": "Claude Opus 5.5",
                        "type": "model",
                        "created_at": "2026-01-01T00:00:00Z",
                    }
                ],
                "has_more": False,
                "first_id": None,
                "last_id": None,
            },
        )

    client = AnthropicClient(
        _config(provider="anthropic", base_url=None),
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )
    models = await client.list_models()
    assert [(m.id, m.label) for m in models] == [("claude-opus-5-5", "Claude Opus 5.5")]
    assert seen[0].url.path == "/v1/models"
    headers = seen[0].headers
    assert SECRET in (headers.get("x-api-key"), (headers.get("authorization") or "")[7:])
    await client.aclose()


def test_secret_redaction_removes_key_like_text() -> None:
    text = f"ошибка {SECRET} и Bearer abcdefghijkl и api_key=zzzzzzzzzzzz"
    cleaned = redact_secrets(text)
    assert SECRET not in cleaned
    assert "abcdefghijkl" not in cleaned
    assert "zzzzzzzzzzzz" not in cleaned
