"""RFC-0005, шаги 1–3: справочник возможностей, бюджет из окна модели, max_tokens и профиль."""

import json
from collections.abc import Coroutine, Iterator
from datetime import date
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import anthropic
import httpx
import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from app.config import Settings
from app.container import Container, build_container
from app.domain.analysis import AnalysisResult, RunContext
from app.domain.models import RunMode, RunStatus, SourceKind
from app.infra.bpmn_tools import MockBpmnTools
from app.infra.events import InMemoryRunEventBus
from app.infra.seed import DEMO_PROJECT_ID
from app.infra.tasks import AsyncioTaskSpawner
from app.llm import capabilities as caps_module
from app.llm import question_analysis
from app.llm.anthropic import AnthropicClient, _map_status
from app.llm.base import ContextOverflowError, PipelineError
from app.llm.capabilities import (
    ANTHROPIC_CATALOG,
    ModelCapabilities,
    RunProfile,
    UnsupportedEffortError,
    capabilities_for,
    checked_profile,
    context_budget_chars,
    from_anthropic_model,
    json_output_tokens,
    nearest_effort,
    wire_effort,
)
from app.llm.client import LlmConfig, ModelInfo
from app.llm.factory import build_pipeline, model_limits
from app.llm.openai import OpenAIClient
from app.llm.openai_compatible import OpenAICompatibleClient
from app.services.common import Runtime
from app.services.errors import InvalidInputError
from app.services.model_resolver import ModelResolver
from app.services.runs import RunService
from tests.llm_helpers import ScriptedPipeline, json_transport, ok_chat
from tests.test_llm_credentials_api import API, BOB, Stack, _call, _create, _settings

SECRET = "sk-test-CAPACITY-0123456789"  # noqa: S105
OPUS_BUDGET = int((1_000_000 - 2 * 128_000 - 16_000) * 2.0 * 0.8)
DEEPSEEK_URL = "https://api.deepseek.com"


@pytest.fixture(autouse=True)
def _clean_registry() -> Iterator[None]:
    caps_module.forget_all()
    yield
    caps_module.forget_all()


@pytest.fixture
def stack() -> Iterator[Stack]:
    s = Stack(_settings())
    with TestClient(s.app):
        yield s


def _config(**kw: Any) -> LlmConfig:
    values: dict[str, Any] = {
        "provider": "anthropic",
        "model": "claude-opus-5-5",
        "api_key": SecretStr(SECRET),
        "base_url": None,
    }
    values.update(kw)
    return LlmConfig(**values)


def _flag(value: bool) -> SimpleNamespace:
    return SimpleNamespace(supported=value)


def _described(model: str, *, window: int, output: int, levels: tuple[str, ...]) -> Any:
    """Описание модели, как его отдаёт Models API Anthropic."""
    effort = {level: _flag(level in levels) for level in ("low", "medium", "high", "max")}
    return SimpleNamespace(
        id=model,
        max_input_tokens=window,
        max_tokens=output,
        capabilities=SimpleNamespace(
            image_input=_flag(True),
            pdf_input=_flag(False),
            effort=SimpleNamespace(supported=True, xhigh=_flag("xhigh" in levels), **effort),
        ),
    )


# ---------- справочник ----------


def test_catalog_describes_claude_5_5_family_with_dated_prices() -> None:
    opus = capabilities_for("anthropic", "claude-opus-5-5")
    assert (opus.context_tokens, opus.max_output_tokens) == (1_000_000, 128_000)
    assert opus.effort_levels == ("low", "medium", "high", "xhigh", "max")
    assert opus.effort_default == "medium"
    assert opus.prices is not None
    assert (opus.prices.input, opus.prices.output, opus.prices.cache_read) == (4.0, 20.0, 0.20)
    assert opus.prices.checked_on == date(2026, 10, 6)
    assert capabilities_for("anthropic", "claude-sonnet-5-5").effort_default == "high"
    haiku = capabilities_for("anthropic", "claude-haiku-5-5")
    assert haiku.effort_default == "medium"
    assert haiku.prices is not None
    assert haiku.prices.note
    assert capabilities_for("anthropic", "claude-fable-5-1").prices.input == 10.0  # type: ignore[union-attr]
    assert capabilities_for("anthropic", "claude-opus-5").prices.output == 25.0  # type: ignore[union-attr]
    # Anthropic не принимает temperature ни у одной модели.
    assert not any(item.accepts_temperature for item in ANTHROPIC_CATALOG.values())
    # До замера `count_tokens` — заведомо низкая оценка для русского текста.
    assert all(item.chars_per_token == 2.0 for item in ANTHROPIC_CATALOG.values())


def test_dated_snapshots_use_the_catalog_entry_of_their_family() -> None:
    opus = ANTHROPIC_CATALOG["claude-opus-5-5"]
    assert capabilities_for("anthropic", "claude-opus-5-5-20261001") is opus
    assert capabilities_for("anthropic", "claude-opus-5-5@20261001") is opus
    assert capabilities_for("anthropic", "claude-opus-5-5-latest") is opus
    assert (
        capabilities_for("anthropic", "claude-opus-5-20260301")
        is ANTHROPIC_CATALOG["claude-opus-5"]
    )
    # Другая модель семейства — не снимок: каталог не угадывает её пределы.
    assert not capabilities_for("anthropic", "claude-opus-5-7").known


def test_unknown_models_get_careful_defaults() -> None:
    old_haiku = capabilities_for("anthropic", "claude-haiku-4-5")
    assert old_haiku.effort_levels == ()
    assert not old_haiku.known
    other = capabilities_for("anthropic", "claude-opus-4-8")
    assert other.effort_levels == ("low", "medium", "high")
    assert other.context_tokens is None
    reasoning = capabilities_for("openai", "o3")
    assert (reasoning.effort_levels, reasoning.accepts_temperature) == (
        ("low", "medium", "high"),
        False,
    )
    classic = capabilities_for("openai", "gpt-4o")
    assert (classic.effort_levels, classic.accepts_temperature) == ((), True)
    assert capabilities_for(
        "openai_compatible", "deepseek-chat", base_url=DEEPSEEK_URL
    ).effort_levels
    assert capabilities_for("deepseek", "anything", base_url=DEEPSEEK_URL).effort_levels
    # DeepSeek через OpenRouter или vLLM не понимает `thinking`: уровней нет.
    assert (
        capabilities_for(
            "openai_compatible", "deepseek/deepseek-chat", base_url="https://openrouter.ai/api/v1"
        ).effort_levels
        == ()
    )
    assert capabilities_for("openai_compatible", "llama-3").effort_levels == ()
    assert capabilities_for("mock", "MockPipeline").effort_levels == ()


def test_models_api_refines_the_catalog_and_is_remembered() -> None:
    refined = from_anthropic_model(
        _described("claude-opus-4-8", window=400_000, output=64_000, levels=("low", "high", "max"))
    )
    assert (refined.context_tokens, refined.max_output_tokens) == (400_000, 64_000)
    assert refined.effort_levels == ("low", "high", "max")
    assert (refined.vision, refined.pdf_input, refined.known) == (True, False, True)
    caps_module.remember("anthropic", "claude-opus-4-8", refined)
    assert capabilities_for("anthropic", "claude-opus-4-8") is refined
    # Описание без возможностей не портит каталог.
    bare = from_anthropic_model(SimpleNamespace(id="claude-opus-5-5"))
    assert bare == ANTHROPIC_CATALOG["claude-opus-5-5"]


async def test_anthropic_model_list_carries_capabilities() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "data": [
                    {
                        "type": "model",
                        "id": "claude-sonnet-5-5",
                        "display_name": "Claude Sonnet 5.5",
                        "created_at": "2026-09-01T00:00:00Z",
                        "max_input_tokens": 1_000_000,
                        "max_tokens": 128_000,
                    }
                ],
                "has_more": False,
                "first_id": None,
                "last_id": None,
            },
        )

    client = AnthropicClient(
        _config(), http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    )
    [model] = await client.list_models()
    assert model.capabilities is not None
    assert model.capabilities.max_output_tokens == 128_000
    assert model.capabilities.effort_default == "high"
    await client.aclose()


# ---------- бюджет и max_tokens ----------


def test_budget_follows_the_window_but_never_drops_below_the_setting() -> None:
    opus = ANTHROPIC_CATALOG["claude-opus-5-5"]
    # Ответ резервируется дважды: repair графа отправляет прежний черновик обратно.
    assert (
        context_budget_chars(opus, fallback_chars=120_000, output_reserve_tokens=128_000)
        == OPUS_BUDGET
    )
    unknown = ModelCapabilities()
    assert (
        context_budget_chars(unknown, fallback_chars=120_000, output_reserve_tokens=16_384)
        == 120_000
    )
    tiny = ModelCapabilities(context_tokens=20_000)
    assert (
        context_budget_chars(tiny, fallback_chars=120_000, output_reserve_tokens=16_384) == 120_000
    )
    capped = context_budget_chars(
        opus, fallback_chars=120_000, output_reserve_tokens=128_000, ceiling_chars=400_000
    )
    assert capped == 400_000


def test_json_max_tokens_uses_model_maximum_unless_capped_explicitly() -> None:
    opus = ANTHROPIC_CATALOG["claude-opus-5-5"]
    assert json_output_tokens(opus, configured=16_384, explicit=False) == 128_000
    assert json_output_tokens(opus, configured=16_384, explicit=True) == 16_384
    assert json_output_tokens(ModelCapabilities(), configured=16_384, explicit=False) == 16_384


def test_settings_know_which_limits_were_set_explicitly() -> None:
    assert not Settings().json_max_tokens_explicit
    assert Settings(llm_json_max_tokens=32_000).json_max_tokens_explicit
    assert Settings().anthropic_effort_default() is None
    assert Settings(llm_anthropic_effort="HIGH").anthropic_effort_default() == "high"
    assert Settings(llm_server_max_effort="Max").llm_server_max_effort == "max"
    with pytest.raises(ValidationError):
        Settings(llm_anthropic_effort="ultra")
    with pytest.raises(ValidationError):
        Settings(llm_server_max_effort="ultra")
    # compose передаёт незаданные переменные пустыми: это «не задано», а не потолок.
    empty = Settings(
        llm_json_max_tokens="",  # type: ignore[arg-type]
        llm_anthropic_effort=" ",
        llm_server_max_effort="",
    )
    assert not empty.json_max_tokens_explicit
    assert empty.anthropic_effort_default() is None
    assert empty.llm_server_max_effort is None


async def test_factory_builds_pipelines_with_model_limits() -> None:
    settings = Settings(mock_delay_scale=0)
    opus = build_pipeline(_config(), settings)
    assert (opus.json_max_tokens, opus.context_budget_chars) == (128_000, OPUS_BUDGET)
    assert opus.chunk_max_tokens == 16_384
    assert opus.effort == "medium"  # умолчание модели уходит провайдеру явно
    await opus.aclose()
    capped = build_pipeline(_config(), Settings(llm_json_max_tokens=16_384))
    assert capped.json_max_tokens == 16_384
    assert capped.context_budget_chars == int((1_000_000 - 2 * 16_384 - 16_000) * 2.0 * 0.8)
    await capped.aclose()
    compatible = build_pipeline(
        _config(provider="openai_compatible", model="llama-3", base_url="https://llm.test/v1"),
        settings,
    )
    assert (compatible.json_max_tokens, compatible.context_budget_chars) == (16_384, 120_000)
    assert compatible.effort is None
    await compatible.aclose()


async def test_chunks_get_a_small_output_limit_and_the_graph_the_full_one() -> None:
    pipeline = ScriptedPipeline(
        complete=lambda _s, _u: "{}", json_max_tokens=128_000, chunk_max_tokens=16_000
    )
    await pipeline._chunk_complete("S", "извлечение, сверка")
    await pipeline._analyze_complete("S", "пакет проекта")
    token = question_analysis._WHOLE_PROJECT.set(True)
    try:
        await pipeline._analyze_complete("S", "весь проект одним пакетом")
    finally:
        question_analysis._WHOLE_PROJECT.reset(token)
    await pipeline._graph_complete("S", "граф")
    calls = pipeline._client.calls  # type: ignore[attr-defined]
    assert [call["max_tokens"] for call in calls] == [16_000, 16_000, 128_000, 128_000]
    assert Settings().llm_chunk_max_tokens == 16_384


# ---------- переход на порции при переполнении окна ----------


async def test_window_overflow_falls_back_to_smaller_portions() -> None:
    pipeline = ScriptedPipeline(fallback_budget_chars=120_000)
    seen: list[int] = []

    async def step(context: RunContext) -> AnalysisResult:
        seen.append(context.analysis_budget_chars)
        if context.analysis_budget_chars > 250_000:
            raise ContextOverflowError("Запрос не поместился в окно модели")
        return AnalysisResult()

    context = RunContext(project_id=UUID(int=1), project_title="П", sources=[], questions=[])
    result = await pipeline._shrinking(replace_budget(context, 1_000_000), step)
    assert seen == [1_000_000, 500_000, 250_000]
    assert result.warnings == [
        "Запрос не поместился в окно модели: материалы обработаны порциями "
        "(бюджет источников уменьшен до 250000 знаков)"
    ]

    async def always(context: RunContext) -> AnalysisResult:
        raise ContextOverflowError("Запрос не поместился в окно модели")

    with pytest.raises(PipelineError, match="даже порциями"):
        await pipeline._shrinking(replace_budget(context, 240_000), always)


def replace_budget(context: RunContext, budget: int) -> RunContext:
    from dataclasses import replace  # noqa: PLC0415 — локальный помощник теста

    return replace(context, analysis_budget_chars=budget)


async def test_adapters_recognise_prompt_too_long() -> None:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    too_long = anthropic.BadRequestError(
        "prompt is too long: 1200000 tokens > 1000000 maximum",
        response=httpx.Response(400, request=request),  # type: ignore[arg-type]
        body=None,
    )
    assert isinstance(_map_status(too_long), ContextOverflowError)
    other = anthropic.BadRequestError(
        "bad",
        response=httpx.Response(400, request=request),  # type: ignore[arg-type]
        body=None,
    )
    assert not isinstance(_map_status(other), ContextOverflowError)

    def handler(_request: httpx.Request) -> httpx.Response:
        body = {"error": {"code": "context_length_exceeded", "message": SECRET}}
        return httpx.Response(400, json=body)

    client = OpenAICompatibleClient(
        _config(provider="openai_compatible", model="m", base_url="https://llm.test/v1"),
        transport=json_transport(handler),
    )
    with pytest.raises(ContextOverflowError) as caught:
        await client.complete("S", "u", json_mode=True, max_tokens=100)
    assert SECRET not in str(caught.value)  # тело ошибки только проверяется
    await client.aclose()


# ---------- effort ----------


def test_nearest_effort_prefers_the_cheaper_neighbour() -> None:
    basic = ("low", "medium", "high")
    assert nearest_effort("max", basic) == "high"
    assert nearest_effort("xhigh", basic) == "high"
    assert nearest_effort("medium", ("low", "high")) == "low"
    assert nearest_effort("high", ()) is None


def test_wire_effort_is_what_the_adapter_sends() -> None:
    opus = ANTHROPIC_CATALOG["claude-opus-5-5"]
    assert wire_effort("anthropic", opus, None) == "medium"
    assert wire_effort("anthropic", opus, None, server_default="low") == "low"
    assert wire_effort("anthropic", opus, "max", server_default="low") == "max"
    o3 = capabilities_for("openai", "o3")
    assert wire_effort("openai", o3, None) is None
    assert wire_effort("openai", o3, "max") == "high"
    assert wire_effort("openai_compatible", ModelCapabilities(), "high") is None


def test_profile_is_checked_against_model_capabilities() -> None:
    opus = ANTHROPIC_CATALOG["claude-opus-5-5"]
    assert checked_profile(RunProfile(effort="xhigh"), opus, "claude-opus-5-5").effort == "xhigh"
    with pytest.raises(UnsupportedEffortError, match="не поддерживает уровень «максимум»"):
        checked_profile(RunProfile(effort="max"), capabilities_for("openai", "o3"), "o3")
    dropped = checked_profile(
        RunProfile(effort="high", semantic_review=False), ModelCapabilities(), "llama"
    )
    assert dropped == RunProfile(effort=None, semantic_review=False)
    assert RunProfile.from_json({"effort": "evil", "semantic_review": "yes"}) == RunProfile()
    assert RunProfile.from_json(None) == RunProfile()


def _openai(model: str, requests: list[httpx.Request]) -> OpenAIClient:
    return OpenAIClient(
        LlmConfig(provider="openai", model=model, api_key=SecretStr(SECRET)),
        transport=json_transport(lambda _r: ok_chat("{}"), requests),
    )


async def test_openai_reasoning_effort_goes_to_the_nearest_level() -> None:
    requests: list[httpx.Request] = []
    reasoning = _openai("o3", requests)
    await reasoning.complete("S", "u", json_mode=True, max_tokens=1000, effort="max")
    await reasoning.complete("S", "u", json_mode=True, max_tokens=1000)
    classic = _openai("gpt-4o", requests)
    await classic.complete("S", "u", json_mode=True, max_tokens=1000, effort="high")
    bodies = [json.loads(r.content) for r in requests]
    assert bodies[0]["reasoning_effort"] == "high"
    assert "temperature" not in bodies[0]
    assert "reasoning_effort" not in bodies[1]
    assert "reasoning_effort" not in bodies[2]
    assert bodies[2]["temperature"] == 0.0
    await reasoning.aclose()
    await classic.aclose()


async def test_deepseek_thinking_only_on_its_own_api_and_medium_keeps_operator_setting() -> None:
    requests: list[httpx.Request] = []

    def compat(base_url: str, model: str, thinking: bool | None) -> OpenAICompatibleClient:
        return OpenAICompatibleClient(
            LlmConfig(
                provider="openai_compatible",
                model=model,
                api_key=SecretStr(SECRET),
                base_url=base_url,
                thinking=thinking,
            ),
            transport=json_transport(lambda _r: ok_chat("{}"), requests),
        )

    # Оператор включил рассуждение (`DEEPSEEK_THINKING_ENABLED=true`).
    deepseek = compat(DEEPSEEK_URL, "deepseek-chat", thinking=True)
    for effort in ("high", "low", "medium", None):
        await deepseek.complete("S", "u", json_mode=True, max_tokens=1000, effort=effort)
    router = compat("https://openrouter.ai/api/v1", "deepseek/deepseek-chat", thinking=None)
    await router.complete("S", "u", json_mode=True, max_tokens=1000, effort="high")
    bodies = [json.loads(r.content) for r in requests]
    assert [b.get("thinking") for b in bodies] == [
        {"type": "enabled"},
        {"type": "disabled"},  # явный low выключает
        {"type": "enabled"},  # medium не выключает включённое оператором
        {"type": "enabled"},  # без профиля — настройка сервера
        None,  # OpenRouter `thinking` не получает
    ]
    assert not any("reasoning_effort" in b for b in bodies)
    await deepseek.aclose()
    await router.aclose()


async def test_profile_copy_passes_effort_and_keeps_subclass_behaviour() -> None:
    class Custom(ScriptedPipeline):
        marker = "custom"

    base = Custom(
        complete=lambda _s, _u: "ответ",
        semantic_review=True,
        capabilities=ANTHROPIC_CATALOG["claude-opus-5-5"],
    )
    derived = base.with_profile(RunProfile(effort="high", semantic_review=False))
    assert isinstance(derived, Custom)
    assert (derived.effort, derived.semantic_review) == ("high", False)
    assert (base.effort, base.semantic_review) == (None, True)
    await derived._complete("S", "u", json_mode=True)
    client = derived._client
    assert client.calls[-1]["effort"] == "high"  # type: ignore[attr-defined]
    assert derived._analysis_model()["effort"] == "high"  # type: ignore[index]
    assert derived._question_analyzer.cache is base._question_analyzer.cache


# ---------- модель сервера ----------


def _server_opus(**options: Any) -> ScriptedPipeline:
    caps, json_max, budget = model_limits(_config(), Settings())
    values: dict[str, Any] = {
        "provider": "anthropic",
        "model": "claude-opus-5-5",
        "capabilities": caps,
        "json_max_tokens": json_max,
        "context_budget_chars": budget,
        "effort": wire_effort("anthropic", caps, None),
        "semantic_review": False,
    }
    values.update(options)
    return ScriptedPipeline(**values)


async def test_server_model_is_capped_by_the_operator() -> None:
    resolver = ModelResolver(None, server_pipeline=_server_opus())
    # Потолок по умолчанию — уровень сервера по умолчанию (у Opus 5.5 — medium).
    with pytest.raises(InvalidInputError, match="не глубже уровня «обычно»"):
        await resolver.resolve(None, profile=RunProfile(effort="high"))
    low = await resolver.resolve(None, profile=RunProfile(effort="low"))
    assert low.pipeline.effort == "low"  # type: ignore[attr-defined]
    # Оператор выключил сверку: включить её на его ключе нельзя, выключить — можно.
    with pytest.raises(InvalidInputError, match="Смысловая сверка"):
        await resolver.resolve(None, profile=RunProfile(semantic_review=True))
    off = await resolver.resolve(None, profile=RunProfile(semantic_review=False))
    assert off.pipeline.semantic_review is False  # type: ignore[attr-defined]
    generous = ModelResolver(
        None, server_pipeline=_server_opus(semantic_review=True), server_max_effort="max"
    )
    deep = await generous.resolve(None, profile=RunProfile(effort="max", semantic_review=True))
    assert (deep.pipeline.effort, deep.pipeline.semantic_review) == ("max", True)  # type: ignore[attr-defined]


def test_server_model_cap_is_configured_by_environment() -> None:
    container = build_container(
        Settings(mock_delay_scale=0, seed_demo_data=False, llm_server_max_effort="high")
    )
    assert container.runs._resolver._server_max_effort == "high"


# ---------- API и прогоны ----------


def test_models_endpoint_returns_capabilities(stack: Stack) -> None:
    stack.user = BOB
    created = _create(stack)
    items = _call(stack, "get", f"/me/llm-credentials/{created['id']}/models").json()["items"]
    by_id = {item["id"]: item["capabilities"] for item in items}
    assert by_id["o3"]["effort_levels"] == ["low", "medium", "high"]
    assert by_id["o3"]["effort_default"] == "medium"
    assert by_id["o3"]["accepts_temperature"] is False
    assert by_id["gpt-4o"]["effort_levels"] == []
    assert by_id["gpt-4o"]["context_tokens"] is None
    assert by_id["gpt-4o"]["known"] is False


def test_models_failure_is_cached_briefly(stack: Stack) -> None:
    stack.user = BOB
    created = _create(stack)
    stack.valid_keys.clear()
    stack.container.llm_credentials._models.clear()
    before = len(stack.requests)
    first = _call(stack, "get", f"/me/llm-credentials/{created['id']}/models")
    second = _call(stack, "get", f"/me/llm-credentials/{created['id']}/models")
    assert (first.status_code, second.status_code) == (422, 422)
    assert first.json() == second.json()
    # Неработающий ключ не дёргает провайдера на каждый показ шапки.
    assert len(stack.requests) == before + 1


def test_server_effort_override_is_reported_as_default() -> None:
    s = Stack(_settings(llm_anthropic_effort="low"))
    with TestClient(s.app):
        service = s.container.llm_credentials
        config = LlmConfig(provider="anthropic", model="-", api_key=SecretStr(SECRET))
        [model] = service._describe(config, [ModelInfo(id="claude-sonnet-5-5", label="x")])
        assert model.capabilities is not None
        assert model.capabilities.effort_default == "low"


def test_unsupported_effort_is_rejected_with_422(stack: Stack) -> None:
    stack.user = BOB
    created = _create(stack, default_model="o3")
    with TestClient(stack.app) as client:
        response = client.post(
            f"{API}/projects/{DEMO_PROJECT_ID}/runs",
            json={
                "mode": RunMode.ANALYZE.value,
                "credential_id": created["id"],
                "profile": {"effort": "max"},
            },
        )
    assert response.status_code == 422
    assert "не поддерживает уровень" in response.json()["detail"]


def test_profile_and_limits_are_stored_and_sent_to_the_provider(stack: Stack) -> None:
    stack.user = BOB
    created = _create(stack, default_model="o3")
    stack.requests.clear()
    with TestClient(stack.app) as client:
        started = client.post(
            f"{API}/projects/{DEMO_PROJECT_ID}/runs",
            json={
                "mode": RunMode.ANALYZE.value,
                "credential_id": created["id"],
                "profile": {"effort": "high", "semantic_review": False},
            },
        )
        assert started.status_code == 202, started.text
        body = started.json()
        assert body["profile"] == {
            "effort": "high",
            "semantic_review": False,
            "budget": None,
            "mode": "pipeline",
            "max_steps": None,
        }
    saved = stack.container.repos.runs._items[UUID(body["id"])]  # type: ignore[attr-defined]
    execution = saved.ir["execution"]
    assert execution["profile"] == {
        "effort": "high",
        "semantic_review": False,
        "budget": None,
        "mode": "pipeline",
        "max_steps": None,
    }
    assert execution["limits"] == {
        "context_budget_chars": 120_000,
        "json_max_tokens": 16_384,
        "effort": "high",
    }
    assert SECRET not in json.dumps(saved.ir, default=str)
    sent = [json.loads(r.content) for r in stack.requests if r.method == "POST"]
    assert sent
    assert all(item["reasoning_effort"] == "high" for item in sent)


def test_model_without_reasoning_ignores_effort(stack: Stack) -> None:
    with TestClient(stack.app) as client:
        started = client.post(
            f"{API}/projects/{DEMO_PROJECT_ID}/runs",
            json={"mode": RunMode.ANALYZE.value, "profile": {"effort": "max"}},
        )
    assert started.status_code == 202, started.text
    assert started.json()["profile"] == {
        "effort": None,
        "semantic_review": None,
        "budget": None,
        "mode": "pipeline",
        "max_steps": None,
    }


# ---------- сквозные прогоны: бюджет модели и восстановление после рестарта ----------


class _HoldSpawner:
    """Прогон принят, но не выполняется: так выглядит процесс, остановленный до старта."""

    def spawn(self, coro: Coroutine[Any, Any, None], *, name: str) -> None:
        coro.close()

    async def cancel(self, *, name: str) -> bool:
        return False

    async def shutdown(self) -> None:
        return None


def _runs(container: Container, pipeline: ScriptedPipeline, spawner: Any) -> RunService:
    resolver = ModelResolver(container.repos, server_pipeline=pipeline, server_max_effort="max")
    return RunService(
        container.repos,
        resolver=resolver,
        bpmn_tools=MockBpmnTools(),
        events=InMemoryRunEventBus(),
        spawner=spawner,
        runtime=Runtime(),
        max_concurrent=2,
    )


async def _project(container: Container) -> UUID:
    view = await container.projects.create(title="Процесс", description=None)
    await container.sources.create_text(
        view.project.id,
        content="1. Принять заявку. Ответственный: оператор.",
        title=None,
        kind=SourceKind.TEXT,
        duration_sec=None,
    )
    return view.project.id


def _claude(model: str, complete: Any = None) -> ScriptedPipeline:
    """Пайплайн Claude с пределами из справочника и записанными ответами вместо сети."""
    config = _config(model=model)
    caps, json_max, budget = model_limits(config, Settings())
    return ScriptedPipeline(
        complete=complete or (lambda _s, _u: "не JSON"),
        provider="anthropic",
        model=model,
        capabilities=caps,
        json_max_tokens=json_max,
        context_budget_chars=budget,
        effort=wire_effort("anthropic", caps, None),
        chunk_max_tokens=16_384,
        fallback_budget_chars=120_000,
    )


def _analysis_requests(container: Container, run_id: UUID) -> list[dict[str, Any]]:
    calls = container.repos.llm_calls._items.values()  # type: ignore[attr-defined]
    return [call.request for call in calls if call.run_id == run_id and call.stage == "analyze"]


async def test_run_context_gets_the_budget_of_its_model() -> None:
    container = build_container(Settings(mock_delay_scale=0, seed_demo_data=False))
    project_id = await _project(container)
    spawner = AsyncioTaskSpawner()
    runs = _runs(container, _claude("claude-opus-5-5"), spawner)
    run = await runs.start(project_id, mode=RunMode.ANALYZE, created_by=None)
    await spawner.wait_idle()
    [request] = _analysis_requests(container, run.id)
    # Сборщик контекста получил бюджет из окна Opus 5.5, а не настройку сервера.
    assert request["context"]["analysis_budget_chars"] == OPUS_BUDGET


async def test_recovery_uses_recorded_limits_of_a_model_outside_the_catalog() -> None:
    model = "claude-opus-4-8"
    described = _described(model, window=400_000, output=64_000, levels=("low", "high", "max"))
    caps_module.remember("anthropic", model, from_anthropic_model(described))
    container = build_container(Settings(mock_delay_scale=0, seed_demo_data=False))
    project_id = await _project(container)
    before = _claude(model)
    run = await _runs(container, before, _HoldSpawner()).start(
        project_id, mode=RunMode.ANALYZE, created_by=None, profile=RunProfile(effort="max")
    )
    recorded = (run.ir or {})["execution"]["limits"]
    expected_budget = int((400_000 - 2 * 64_000 - 16_000) * 2.0 * 0.8)
    assert recorded == {
        "context_budget_chars": expected_budget,
        "json_max_tokens": 64_000,
        "effort": "max",
    }

    # Рестарт: уточнения Models API потеряны, модель снова «неизвестна» (окно и max не знаем).
    caps_module.forget_all()
    after = _claude(model)
    assert after.context_budget_chars == 120_000
    spawner = AsyncioTaskSpawner()
    restarted = _runs(container, after, spawner)
    restarted.resume(run.id)
    await spawner.wait_idle()
    [request] = _analysis_requests(container, run.id)
    assert request["context"]["analysis_budget_chars"] == expected_budget
    sent = after._client.calls  # type: ignore[attr-defined]
    assert sent
    # Весь проект одним пакетом — полный записанный максимум и записанный уровень.
    assert {(call["effort"], call["max_tokens"]) for call in sent} == {("max", 64_000)}


async def test_recovery_stops_when_the_model_no_longer_allows_recorded_limits() -> None:
    model = "claude-opus-4-8"
    described = _described(model, window=400_000, output=64_000, levels=("low", "high", "max"))
    caps_module.remember("anthropic", model, from_anthropic_model(described))
    container = build_container(Settings(mock_delay_scale=0, seed_demo_data=False))
    project_id = await _project(container)
    run = await _runs(container, _claude(model), _HoldSpawner()).start(
        project_id, mode=RunMode.ANALYZE, created_by=None, profile=RunProfile(effort="max")
    )
    # После рестарта провайдер описывает модель иначе: уровня «максимум» больше нет.
    caps_module.forget_all()
    narrowed = _described(model, window=400_000, output=64_000, levels=("low", "high"))
    caps_module.remember("anthropic", model, from_anthropic_model(narrowed))
    after = _claude(model)
    spawner = AsyncioTaskSpawner()
    restarted = _runs(container, after, spawner)
    restarted.resume(run.id)
    await spawner.wait_idle()
    saved = await restarted.get(run.id)
    assert saved.status is RunStatus.FAILED
    assert saved.error is not None
    assert "Пределы модели изменились" in saved.error
    assert after._client.calls == []  # type: ignore[attr-defined]
