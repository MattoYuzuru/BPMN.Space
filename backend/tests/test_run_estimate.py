"""Стоимость прогона и оценка до запуска (RFC-0005, шаг 4): план, цены, кеш и API."""

from datetime import date
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.container import Container
from app.domain.models import LlmCall, LlmCallTotals, RunMode
from app.domain.runs import RunCost
from app.infra.repositories.memory import InMemoryStore
from app.llm.base import LlmUsage
from app.llm.capabilities import ModelCapabilities, ModelPrices
from app.llm.estimate import (
    CostRange,
    EstimateInput,
    IntRange,
    UsageCost,
    cost_of_usage,
    estimate_run,
)
from tests.conftest import API, add_text, create_project, read_events
from tests.llm_helpers import ScriptedPipeline

PRICES = ModelPrices(
    input=4.0,
    output=20.0,
    cache_read=0.2,
    cache_write=5.0,
    checked_on=date(2026, 10, 6),
)
CAPABILITIES = ModelCapabilities(
    context_tokens=1_000_000,
    max_output_tokens=128_000,
    prices=PRICES,
    chars_per_token=2.0,
    known=True,
)


def _inputs(**changes: object) -> EstimateInput:
    values: dict[str, object] = {
        "mode": RunMode.BUILD,
        "source_chars": 10_000,
        "budget_chars": 120_000,
        "chunk_chars": 24_000,
        "current_xml_chars": 0,
        "questions": 3,
        "semantic_review": False,
        "json_max_tokens": 128_000,
        "chunk_max_tokens": 16_384,
        "capabilities": CAPABILITIES,
        "effort": None,
        "chars_per_token": None,
    }
    values.update(changes)
    return EstimateInput(**values)  # type: ignore[arg-type]


# ---------- чистый планировщик ----------


def test_whole_project_estimate_is_a_range_with_prices() -> None:
    estimate = estimate_run(_inputs())
    assert estimate.complete is True
    assert estimate.priced_on == date(2026, 10, 6)
    assert estimate.tokens.min > 0
    assert estimate.tokens.max > estimate.tokens.min
    assert estimate.calls.min >= 1
    assert estimate.calls.max > estimate.calls.min
    assert estimate.cost is not None
    assert estimate.cost.min_usd is not None
    assert estimate.cost.max_usd is not None
    assert 0 < estimate.cost.min_usd <= estimate.cost.max_usd
    assert [item.stage for item in estimate.breakdown] == ["analyze", "structure"]
    assert estimate.duration_sec.min < estimate.duration_sec.max


def test_chunked_project_adds_evidence_and_more_calls() -> None:
    fit = estimate_run(_inputs())
    chunked = estimate_run(_inputs(source_chars=500_000))
    assert "evidence" in [item.stage for item in chunked.breakdown]
    assert chunked.calls.min > fit.calls.min
    assert chunked.tokens.max > fit.tokens.max


def test_unknown_prices_mean_incomplete_estimate() -> None:
    estimate = estimate_run(_inputs(capabilities=ModelCapabilities(chars_per_token=2.0)))
    assert estimate.complete is False
    assert estimate.cost is None
    assert estimate.priced_on is None
    assert any("complete=false" in note for note in estimate.notes)


def test_semantic_review_and_effort_change_the_plan() -> None:
    plain = estimate_run(_inputs())
    review = estimate_run(_inputs(semantic_review=True))
    assert "review" in [item.stage for item in review.breakdown]
    assert review.tokens.max > plain.tokens.max
    low = estimate_run(_inputs(effort="low"))
    high = estimate_run(_inputs(effort="max"))
    assert high.tokens.max > low.tokens.max


def test_analyze_mode_has_no_structure_stage() -> None:
    estimate = estimate_run(_inputs(mode=RunMode.ANALYZE))
    assert [item.stage for item in estimate.breakdown] == ["analyze"]


def test_range_rejects_invalid_bounds() -> None:
    with pytest.raises(ValueError, match="диапазон"):
        IntRange(min=5, max=1)


def test_cost_of_usage_uses_cache_prices() -> None:
    usage = LlmUsage(
        tokens_in=1_000,
        tokens_out=100,
        cache_read_tokens=600,
        cache_write_tokens=100,
        requests=1,
    )
    cost = cost_of_usage(usage, PRICES)
    assert cost.complete is True
    assert cost.checked_on == date(2026, 10, 6)
    # (300 × 4 + 600 × 0,2 + 100 × 5 + 100 × 20) / 1 млн
    assert cost.cost_usd == round((300 * 4 + 600 * 0.2 + 100 * 5 + 100 * 20) / 1_000_000, 6)


def test_cost_of_usage_is_incomplete_without_prices() -> None:
    usage = LlmUsage(tokens_in=100, tokens_out=10, requests=1)
    cost: UsageCost = cost_of_usage(usage, None)
    assert cost.cost_usd is None
    assert cost.complete is False
    assert cost_of_usage(LlmUsage(), PRICES).cost_usd is None


# ---------- репозиторий вызовов модели ----------


async def test_memory_totals_group_by_stage_and_sum_cost() -> None:
    repos = InMemoryStore().repositories()
    run_id = uuid4()
    await _add_calls(repos.llm_calls, run_id)
    totals = await repos.llm_calls.totals(run_id)
    assert totals.calls == 2
    assert totals.usage_calls == 2
    assert totals.priced_calls == 2
    assert (totals.tokens_in, totals.tokens_out) == (1_100, 110)
    assert totals.cost_usd == 0.5
    assert set(totals.stages) == {"analyze", "structure"}
    assert totals.complete is True
    listed = await repos.llm_calls.list_by_run(run_id)
    assert [call.stage for call in listed] == ["analyze", "structure"]

    model = RunCost.of(totals)
    assert model is not None
    assert model.by_stage[0].label == "Сверка вопросов"
    assert model.cost_usd == 0.5


async def _add_calls(repo, run_id: UUID) -> None:
    await repo.add(
        LlmCall(
            id=uuid4(),
            run_id=run_id,
            stage="analyze",
            request={},
            response={},
            tokens_in=1_000,
            tokens_out=100,
            cache_read_tokens=600,
            cache_write_tokens=100,
            cost_usd=0.25,
            price_checked_on=date(2026, 10, 6),
            model="claude-opus-5-5",
        )
    )
    await repo.add(
        LlmCall(
            id=uuid4(),
            run_id=run_id,
            stage="structure",
            request={},
            response={},
            tokens_in=100,
            tokens_out=10,
            cost_usd=0.25,
        )
    )


# ---------- API оценки ----------


def test_estimate_endpoint_for_mock_is_incomplete(client: TestClient) -> None:
    project_id = create_project(client)
    add_text(client, project_id, "Оператор принимает заявку. Руководитель согласует заявку.")
    response = client.post(f"{API}/projects/{project_id}/runs/estimate", json={"mode": "build"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["complete"] is False
    assert body["cost"] is None
    assert body["tokens"]["min"] <= body["tokens"]["max"]
    assert body["duration"]["min_sec"] <= body["duration"]["max_sec"]
    stages = [item["stage"] for item in body["breakdown"]]
    assert stages == ["analyze", "structure", "review"]
    assert any("не входит" in note for note in body["notes"])


def test_estimate_endpoint_with_prices_is_complete(
    client: TestClient, container: Container
) -> None:
    container.estimate._resolver.server_pipeline = ScriptedPipeline(
        provider="anthropic",
        model="claude-opus-5-5",
        capabilities=CAPABILITIES,
        complete=lambda _s, _u: "{}",
    )
    project_id = create_project(client)
    add_text(client, project_id, "Инженер готовит заявку. " * 200)
    response = client.post(f"{API}/projects/{project_id}/runs/estimate", json={"mode": "build"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["complete"] is True
    assert body["cost"]["currency"] == "USD"
    assert 0 < body["cost"]["min_usd"] <= body["cost"]["max_usd"]
    assert body["priced_on"] == "2026-10-06"
    assert body["model"] == "claude-opus-5-5"
    assert body["provider"] == "anthropic"
    assert any("count_tokens" in note for note in body["notes"])


def test_estimate_endpoint_errors(client: TestClient) -> None:
    missing = "00000000-0000-0000-0000-000000000000"
    assert (
        client.post(f"{API}/projects/{missing}/runs/estimate", json={"mode": "build"}).status_code
        == 404
    )
    project_id = create_project(client)
    empty = client.post(f"{API}/projects/{project_id}/runs/estimate", json={"mode": "build"})
    assert empty.status_code == 422
    assert "источник" in empty.json()["detail"]
    bad = client.post(f"{API}/projects/{project_id}/runs/estimate", json={"mode": "deploy"})
    assert bad.status_code == 422


# ---------- стоимость прогона в API и SSE ----------


def test_run_keeps_cost_after_calls_and_shows_it_in_api(
    client: TestClient, container: Container
) -> None:
    project_id = create_project(client)
    add_text(client, project_id, "Оператор принимает заявку. Руководитель согласует заявку.")
    run = client.post(f"{API}/projects/{project_id}/runs", json={"mode": "analyze"}).json()
    events = read_events(client, run["id"])
    usage_events = [data for kind, data in events if kind == "usage"]
    assert usage_events, "событие usage должно приходить после этапа с вызовами модели"
    assert usage_events[-1]["calls"] == 1
    done = events[-1][1]["run"]
    assert done["cost"]["calls"] == 1
    assert done["cost"]["cost_usd"] is None  # mock не сообщает токены и цены
    assert done["cost"]["complete"] is False

    # Провайдер сообщил токены: агрегат стоимости виден и в GET прогона.
    assert client.portal is not None
    client.portal.call(
        container.repos.llm_calls.add,
        LlmCall(
            id=uuid4(),
            run_id=UUID(run["id"]),
            stage="analyze",
            request={},
            response={},
            tokens_in=1_000,
            tokens_out=100,
            cache_read_tokens=600,
            cost_usd=0.25,
            price_checked_on=date(2026, 10, 6),
            model="claude-opus-5-5",
        ),
    )
    stored = client.get(f"{API}/runs/{run['id']}").json()
    cost = stored["cost"]
    assert cost["tokens_in"] == 1_000
    assert cost["cache_read_tokens"] == 600
    assert cost["cost_usd"] == 0.25
    assert cost["complete"] is False  # у mock-вызова нет токенов и цены
    assert [item["stage"] for item in cost["by_stage"]] == ["analyze"]
    assert cost["by_stage"][0]["label"] == "Сверка вопросов"


def test_run_cost_is_none_without_calls() -> None:
    assert RunCost.of(LlmCallTotals()) is None
    assert CostRange(min_usd=None, max_usd=None).currency == "USD"
