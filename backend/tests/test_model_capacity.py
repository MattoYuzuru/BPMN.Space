"""RFC-0005, шаги 1–3: справочник возможностей, бюджет из окна модели, max_tokens и профиль."""

import json
from collections.abc import Iterator
from datetime import date
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import httpx
import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from app.config import Settings
from app.container import build_container
from app.domain.models import RunMode
from app.infra.seed import DEMO_PROJECT_ID
from app.llm import capabilities as caps_module
from app.llm.anthropic import AnthropicClient
from app.llm.base import PipelineError
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
)
from app.llm.client import LlmConfig, ModelInfo
from app.llm.factory import build_pipeline
from app.llm.openai import OpenAIClient
from app.llm.openai_compatible import OpenAICompatibleClient
from app.services.runs import _RunState
from tests.llm_helpers import ScriptedPipeline, json_transport, ok_chat
from tests.test_llm_credentials_api import API, BOB, Stack, _call, _create, _settings

SECRET = "sk-test-CAPACITY-0123456789"  # noqa: S105
OPUS_BUDGET = int((1_000_000 - 128_000 - 16_000) * 2.5 * 0.8)


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
    assert all(item.chars_per_token == 2.5 for item in ANTHROPIC_CATALOG.values())


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
    assert capabilities_for("openai_compatible", "deepseek-chat").effort_levels
    assert capabilities_for(
        "deepseek", "anything", base_url="https://api.deepseek.com"
    ).effort_levels
    assert capabilities_for("openai_compatible", "llama-3").effort_levels == ()
    assert capabilities_for("mock", "MockPipeline").effort_levels == ()


def test_models_api_refines_the_catalog_and_is_remembered() -> None:
    def flag(value: bool) -> SimpleNamespace:
        return SimpleNamespace(supported=value)

    item = SimpleNamespace(
        id="claude-opus-4-8",
        max_input_tokens=400_000,
        max_tokens=64_000,
        capabilities=SimpleNamespace(
            image_input=flag(True),
            pdf_input=flag(False),
            effort=SimpleNamespace(
                supported=True,
                low=flag(True),
                medium=flag(True),
                high=flag(True),
                xhigh=None,
                max=flag(True),
            ),
        ),
    )
    refined = from_anthropic_model(item)
    assert (refined.context_tokens, refined.max_output_tokens) == (400_000, 64_000)
    assert refined.effort_levels == ("low", "medium", "high", "max")
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
    with pytest.raises(ValidationError):
        Settings(llm_anthropic_effort="ultra")
    # compose передаёт незаданные переменные пустыми: это «не задано», а не потолок.
    empty = Settings(llm_json_max_tokens="", llm_anthropic_effort=" ")  # type: ignore[arg-type]
    assert not empty.json_max_tokens_explicit
    assert empty.anthropic_effort_default() is None


async def test_factory_builds_pipelines_with_model_limits() -> None:
    settings = Settings(mock_delay_scale=0)
    opus = build_pipeline(_config(), settings)
    assert (opus.json_max_tokens, opus.context_budget_chars) == (128_000, OPUS_BUDGET)
    await opus.aclose()
    capped = build_pipeline(_config(), Settings(llm_json_max_tokens=16_384))
    assert capped.json_max_tokens == 16_384
    assert capped.context_budget_chars == int((1_000_000 - 16_384 - 16_000) * 2.5 * 0.8)
    await capped.aclose()
    compatible = build_pipeline(
        _config(provider="openai_compatible", model="llama-3", base_url="https://llm.test/v1"),
        settings,
    )
    assert (compatible.json_max_tokens, compatible.context_budget_chars) == (16_384, 120_000)
    await compatible.aclose()


def test_run_uses_the_budget_of_its_model() -> None:
    container = build_container(Settings(mock_delay_scale=0, seed_demo_data=False))
    runs = container.runs
    wide = ScriptedPipeline(context_budget_chars=900_000)
    assert runs._budget(_RunState(pipeline=wide)) == 900_000
    assert runs._budget(_RunState(pipeline=ScriptedPipeline())) == 120_000
    assert runs._budget(_RunState(pipeline=runs._pipeline)) == 120_000


# ---------- effort ----------


def test_nearest_effort_prefers_the_cheaper_neighbour() -> None:
    basic = ("low", "medium", "high")
    assert nearest_effort("max", basic) == "high"
    assert nearest_effort("xhigh", basic) == "high"
    assert nearest_effort("medium", ("low", "high")) == "low"
    assert nearest_effort("high", ()) is None


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


async def test_deepseek_thinking_follows_effort_and_others_ignore_it() -> None:
    requests: list[httpx.Request] = []

    def compat(model: str, thinking: bool | None = None) -> OpenAICompatibleClient:
        return OpenAICompatibleClient(
            LlmConfig(
                provider="openai_compatible",
                model=model,
                api_key=SecretStr(SECRET),
                base_url="https://llm.test/v1",
                thinking=thinking,
            ),
            transport=json_transport(lambda _r: ok_chat("{}"), requests),
        )

    deepseek = compat("deepseek-chat", thinking=False)
    for effort in ("high", "low", None):
        await deepseek.complete("S", "u", json_mode=True, max_tokens=1000, effort=effort)
    other = compat("llama-3")
    await other.complete("S", "u", json_mode=True, max_tokens=1000, effort="max")
    bodies = [json.loads(r.content) for r in requests]
    assert [b.get("thinking") for b in bodies] == [
        {"type": "enabled"},
        {"type": "disabled"},
        {"type": "disabled"},  # без профиля — настройка сервера
        None,
    ]
    assert not any("reasoning_effort" in b for b in bodies)
    await deepseek.aclose()
    await other.aclose()


async def test_profile_copy_passes_effort_and_keeps_subclass_behaviour() -> None:
    class Custom(ScriptedPipeline):
        marker = "custom"

    base = Custom(complete=lambda _s, _u: "ответ", semantic_review=True)
    derived = base.with_profile(RunProfile(effort="high", semantic_review=False))
    assert isinstance(derived, Custom)
    assert derived.profile == RunProfile(effort="high", semantic_review=False)
    assert base.profile == RunProfile(effort=None, semantic_review=True)
    await derived._complete("S", "u", json_mode=True)
    client = derived._client
    assert client.calls[-1]["effort"] == "high"  # type: ignore[attr-defined]
    assert derived._analysis_model()["effort"] == "high"  # type: ignore[index]
    assert derived._question_analyzer.cache is base._question_analyzer.cache


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


def test_profile_is_stored_in_execution_and_sent_to_the_provider(stack: Stack) -> None:
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
        assert body["profile"] == {"effort": "high", "semantic_review": False}
    saved = stack.container.repos.runs._items[UUID(body["id"])]  # type: ignore[attr-defined]
    assert saved.ir["execution"]["profile"] == {"effort": "high", "semantic_review": False}
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
    assert started.json()["profile"] == {"effort": None, "semantic_review": None}


async def test_recovery_reuses_the_recorded_profile(stack: Stack) -> None:
    stack.user = BOB
    created = _create(stack, default_model="o3")
    runs = stack.container.runs
    run = await runs.start(
        DEMO_PROJECT_ID,
        mode=RunMode.ANALYZE,
        created_by=BOB.id,
        credential_id=UUID(created["id"]),
        profile=RunProfile(effort="low"),
    )
    await stack.container.spawner.wait_idle()
    run = await runs.get(run.id)
    # «после рестарта»: пайплайн потерян, профиль берётся из ir.execution
    restored = await runs._run_pipeline(run)
    assert restored.profile.effort == "low"
    assert restored.pipeline.profile.effort == "low"  # type: ignore[attr-defined]
    state = _RunState(pipeline=restored.pipeline)
    execution = dict((run.ir or {})["execution"])
    execution.pop("source_snapshot_hash")
    no_hash: Any = SimpleNamespace(source_snapshot_hash=None)
    runs._check_recovered_input(run, no_hash, execution, state)
    execution["profile"] = {"effort": "high", "semantic_review": None}
    with pytest.raises(PipelineError, match="Профиль модели изменился"):
        runs._check_recovered_input(run, no_hash, execution, state)
    await restored.release()
