"""Агентный режим RFC-0004 на записанных ответах: цикл, инструменты, бюджет и восстановление.

Живой провайдер не нужен: `RecordedToolClient` отдаёт записанные `tool_use`/`tool_calls`, а
сервер выполняет настоящие инструменты и проверки. Тесты покрывают цикл до submit, границы
чтения, дословные цитаты вопросов, отклонение и повтор IR, мягкую остановку по бюджету,
отмену, журнал `llm_calls` без текстов источников и продолжение после рестарта (ADR-0008).
"""

import asyncio
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.container import Container, build_container
from app.domain.analysis import ContextSource, RunContext
from app.domain.bpmn.ir import GraphIR
from app.domain.models import (
    Project,
    QuestionCategory,
    QuestionKind,
    Run,
    RunMode,
    RunStatus,
    Severity,
    Source,
    SourceKind,
    SourceStatus,
    TechnicalQuestionKind,
)
from app.domain.sources import SourceSearchHit
from app.infra.bpmn_tools import MockBpmnTools
from app.infra.events import InMemoryRunEventBus
from app.infra.repositories.memory import InMemoryStore
from app.infra.tasks import AsyncioTaskSpawner
from app.llm.agent import (
    AGENT_PROMPT_VERSION,
    AgentInput,
    AgentLimits,
    AgentQuestionView,
    AgentRunner,
    AgentSource,
    AgentTurn,
    build_system_prompt,
    tool_definitions,
)
from app.llm.base import BudgetReachedError, PipelineError, run_budget, track_run_usage
from app.llm.capabilities import Budget, ModelCapabilities, ModelPrices, RunProfile
from app.llm.estimate import EstimateInput, estimate_run
from app.llm.mock import RecordedToolClient
from app.llm.pipeline import LlmPipeline, verified_quote
from app.llm.tools import ToolTurn, ToolUse
from app.main import create_app
from app.services.agent_run import (
    check_submitted_graph,
    recorded_state,
    started_record,
)
from app.services.common import Runtime
from app.services.errors import InvalidInputError
from app.services.model_resolver import ModelResolver
from app.services.runs import RunService
from tests.test_graph_ir import PROOF, SOURCE_ID, TEXT, graph_case

PRICES = ModelPrices(
    input=4.0, output=20.0, cache_read=0.2, cache_write=5.0, checked_on=date(2026, 10, 6)
)
CAPABILITIES = ModelCapabilities(
    context_tokens=1_000_000,
    max_output_tokens=128_000,
    tools=True,
    prices=PRICES,
    chars_per_token=2.0,
    known=True,
)
QUESTION = {
    "text": "Кто согласует заявку, если документы неполные?",
    "assumption": "Считаем, что возвращает оператор",
    "kind": "unclear_order",
    "severity": "major",
    "quotes": [PROOF],
}


def _context() -> RunContext:
    source = ContextSource(
        id=SOURCE_ID,
        kind=SourceKind.TEXT,
        title="Регламент",
        content=TEXT,
        created_at=datetime(2026, 11, 4, tzinfo=UTC),
    )
    return RunContext(
        project_id=uuid4(),
        project_title="Проверка заявки",
        sources=[source],
        questions=[],
        evidence_sources=[source],
        analysis_budget_chars=120_000,
    )


def _agent_input(
    *, mode: RunMode = RunMode.BUILD, steps_spent: int = 0, **limits: Any
) -> AgentInput:
    return AgentInput(
        project_title="Проверка заявки",
        project_description=None,
        mode=mode,
        sources=(
            AgentSource(
                id=SOURCE_ID,
                title="Регламент",
                kind=SourceKind.TEXT,
                content=TEXT,
                created_at=datetime(2026, 11, 4, tzinfo=UTC),
            ),
        ),
        questions=(
            AgentQuestionView(
                code="Q-1",
                status="open",
                kind="missing_actor",
                text="Кто проверяет заявку?",
                assumption="Оператор",
            ),
        ),
        limits=AgentLimits(max_steps=limits.pop("max_steps", 8), **limits),
        steps_spent=steps_spent,
    )


def use(name: str, arguments: dict[str, Any], *, call_id: str | None = None) -> ToolUse:
    return ToolUse(
        id=call_id or f"call_{name}_{uuid4().hex[:6]}",
        name=name,
        arguments=json.dumps(arguments, ensure_ascii=False),
    )


def turn(*uses: ToolUse, text: str | None = None) -> ToolTurn:
    return ToolTurn(text=text, tool_uses=uses, stop_reason="tool_use" if uses else "end_turn")


def _verify(sources: list[ContextSource], source_id: object, quote: object):
    return verified_quote(sources, source_id, quote)


async def _no_search(_query: str) -> list[Any]:
    return []


async def _check_graph(data: object):
    return await check_submitted_graph(data, _context(), _verify, lint=MockBpmnTools().lint)


def _runner(
    client: RecordedToolClient,
    *,
    task: AgentInput | None = None,
    search: Any = None,
    check_graph: Any = None,
    on_turn: Any = None,
) -> AgentRunner:
    return AgentRunner(
        client,
        task or _agent_input(),
        verify_quote=_verify,
        search=search or _no_search,
        check_graph=check_graph or _check_graph,
        on_turn=on_turn,
        max_tokens=8_192,
        effort="medium",
        capabilities=CAPABILITIES,
    )


def _tool_results(client: RecordedToolClient, *, limit: int | None = None) -> list[dict[str, Any]]:
    """Уникальные результаты инструментов, которые модель уже получила, по порядку вызовов.

    Результат последнего `submit`, принятого цикла, модели не отправляется (разговор закончен),
    поэтому проверяется по `AgentOutcome`, а не здесь.
    """
    results: list[dict[str, Any]] = []
    seen: set[str | None] = set()
    for call in client.calls:
        for message in call["messages"]:  # type: ignore[union-attr]
            if message.role != "tool" or message.tool_use_id in seen:
                continue
            seen.add(message.tool_use_id)
            results.append(json.loads(message.text))
    return results[-limit:] if limit is not None else results


def _broken_ir() -> dict[str, Any]:
    data = graph_case("xor")
    data["flows"] = [flow for flow in data["flows"] if flow["id"] != "F3"]
    return data


# ---------- порт провайдера: записанные tool_use/tool_calls ----------


@pytest.mark.asyncio
async def test_recorded_tool_client_returns_turns_and_records_usage() -> None:
    client = RecordedToolClient([turn(use("list_sources", {})), turn()], usage=(11, 7, 0, 0))
    with track_run_usage() as totals:
        first = await client.complete_with_tools("s", [], [], max_tokens=10)
    assert first.tool_uses[0].name == "list_sources"
    assert totals.requests == 1
    assert (totals.tokens_in, totals.tokens_out) == (11, 7)
    with pytest.raises(RuntimeError, match="отвечает только на агентные ходы"):
        await client.complete("s", "u", json_mode=True, max_tokens=10)


def test_tool_definitions_reflect_read_limit() -> None:
    tools = {tool.name: tool for tool in tool_definitions(AgentLimits(read_max_chars=2_000))}
    assert set(tools) == {
        "list_sources",
        "read_source",
        "search_sources",
        "list_questions",
        "propose_question",
        "check_graph",
        "submit",
    }
    read = tools["read_source"].input_schema["properties"]
    assert read["limit"]["maximum"] == 2_000
    submit = tools["submit"].input_schema
    assert "questions" in submit["properties"]
    assert "ir" in submit["properties"]


def test_system_prompt_is_versioned_and_forbids_source_instructions() -> None:
    prompt = build_system_prompt()
    assert AGENT_PROMPT_VERSION in prompt
    assert "недоверенные ДАННЫЕ" in prompt
    assert "submit" in prompt
    assert "JSON Schema IR" in prompt
    assert "плейбук" in prompt.lower() or "ПЛЕЙБУКИ" in prompt


# ---------- агентный цикл ----------


@pytest.mark.asyncio
async def test_agent_reads_sources_and_submits_checked_graph() -> None:
    graph = graph_case("xor")
    client = RecordedToolClient(
        [
            turn(use("list_sources", {})),
            turn(use("read_source", {"source_id": str(SOURCE_ID), "from": 0, "limit": 200})),
            turn(use("propose_question", QUESTION)),
            turn(use("check_graph", {"ir": graph})),
            turn(use("submit", {"questions": [QUESTION], "ir": graph})),
        ]
    )
    turns: list[AgentTurn] = []

    async def on_turn(record: AgentTurn) -> None:
        turns.append(record)

    outcome = await _runner(client, on_turn=on_turn).run()
    assert outcome.draft is not None
    assert GraphIR.model_validate(outcome.draft.ir)  # канонический IR проверяем
    assert len(outcome.analysis.new_questions) == 1
    question = outcome.analysis.new_questions[0]
    assert question.kind is QuestionKind.UNCLEAR_ORDER
    assert question.severity is Severity.MAJOR
    assert question.about is not None
    assert question.about.quote in TEXT
    assert outcome.steps == 5
    assert len(turns) == 5
    assert turns[-1].tool_names == ("submit",)
    assert all(record.usage.requests == 0 for record in turns)  # клиент без usage
    # Журнал содержит имена и хеши, но не тексты источников.
    recorded = json.dumps([record.journal for record in turns], ensure_ascii=False)
    assert "read_source" in recorded
    assert TEXT not in recorded
    # Модель увидела результат проверки и оглавление.
    results = _tool_results(client)
    assert results[1]["text"].startswith("Оператор проверяет")
    assert results[3]["ok"] is True


@pytest.mark.asyncio
async def test_agent_retries_after_rejected_graph_and_cannot_skip_submit_checks() -> None:
    good = graph_case("xor")
    broken = _broken_ir()
    client = RecordedToolClient(
        [
            turn(use("check_graph", {"ir": broken})),
            turn(use("submit", {"questions": [], "ir": broken})),
            turn(use("check_graph", {"ir": good})),
            turn(use("submit", {"questions": [], "ir": good})),
        ]
    )
    outcome = await _runner(client).run()
    assert outcome.draft is not None
    results = _tool_results(client)
    # Первые две попытки отклонены адресными ошибками, проект не изменён.
    assert results[0]["ok"] is False
    assert results[0]["errors"]
    assert results[1]["ok"] is False
    assert results[2]["ok"] is True
    assert outcome.steps == 4


@pytest.mark.asyncio
async def test_agent_requires_ir_for_build_and_accepts_analyze_without_it() -> None:
    client = RecordedToolClient(
        [
            turn(use("submit", {"questions": [QUESTION]})),
            turn(use("submit", {"questions": [QUESTION], "ir": graph_case("xor")})),
        ]
    )
    build_outcome = await _runner(client).run()
    assert build_outcome.draft is not None
    first = _tool_results(client)[0]
    assert first["ok"] is False
    assert "ir" in json.dumps(first, ensure_ascii=False)

    analyze_client = RecordedToolClient([turn(use("submit", {"questions": [QUESTION]}))])
    analyze_outcome = await _runner(analyze_client, task=_agent_input(mode=RunMode.ANALYZE)).run()
    assert analyze_outcome.draft is None
    assert len(analyze_outcome.analysis.new_questions) == 1


@pytest.mark.asyncio
async def test_agent_propose_question_checks_quotes_verbatim() -> None:
    invented = {**QUESTION, "quotes": [{"source_id": str(SOURCE_ID), "quote": "выдуманный факт"}]}
    client = RecordedToolClient(
        [
            turn(use("propose_question", invented)),
            turn(use("propose_question", QUESTION)),
            turn(use("submit", {"questions": [{"proposal_id": "P-1"}]})),
        ]
    )
    outcome = await _runner(client, task=_agent_input(mode=RunMode.ANALYZE)).run()
    results = _tool_results(client)
    assert results[0]["ok"] is False
    assert any("дословно" in error for error in results[0]["errors"])
    assert results[1]["ok"] is True
    assert results[1]["proposal_id"] == "P-1"
    # P-1 — второе предложение: первое отклонено и не зарегистрировано.
    assert results[1]["quotes"][0]["quote"] == TEXT
    assert len(outcome.analysis.new_questions) == 1


@pytest.mark.asyncio
async def test_agent_read_source_bounds_and_limits() -> None:
    tool_input = {"source_id": str(SOURCE_ID)}
    client = RecordedToolClient(
        [
            turn(use("read_source", {"source_id": str(uuid4())})),
            turn(use("read_source", {**tool_input, "from": len(TEXT) + 10})),
            turn(use("read_source", {**tool_input, "from": -1})),
            turn(use("read_source", {**tool_input, "limit": 100_000})),
            turn(use("read_source", {**tool_input, "from": 10, "limit": 20})),
            turn(use("submit", {"questions": []})),
        ]
    )
    await _runner(client, task=_agent_input(mode=RunMode.ANALYZE)).run()
    results = _tool_results(client)
    assert results[0]["ok"] is False
    assert "Неизвестный source_id" in results[0]["error"]
    assert results[1]["ok"] is False
    assert "за концом текста" in results[1]["error"]
    assert results[2]["ok"] is False
    capped = results[3]
    assert capped["ok"] is True
    assert capped["to"] - capped["from"] == min(AgentLimits().read_max_chars, len(TEXT))
    assert len(capped["text"]) == len(TEXT)
    assert capped["next_from"] is None
    exact = results[4]
    assert exact["text"] == TEXT[10:30]
    assert exact["to"] == 30
    assert exact["next_from"] == 30


@pytest.mark.asyncio
async def test_agent_search_sources_returns_ranked_snippets() -> None:
    async def search(query: str) -> list[SourceSearchHit]:
        assert query == "заявка"
        return [
            SourceSearchHit(source_id=SOURCE_ID, title="Регламент", snippet="…заявку…", rank=0.7)
        ]

    client = RecordedToolClient(
        [
            turn(use("search_sources", {"query": "заявка"})),
            turn(use("search_sources", {"query": "х"})),
            turn(use("submit", {"questions": []})),
        ]
    )
    await _runner(client, task=_agent_input(mode=RunMode.ANALYZE), search=search).run()
    results = _tool_results(client)
    assert results[0]["ok"] is True
    assert results[0]["results"][0]["source_id"] == str(SOURCE_ID)
    assert results[1]["ok"] is False  # минимум 2 символа


@pytest.mark.asyncio
async def test_agent_answers_without_tools_are_nudged_then_fail() -> None:
    client = RecordedToolClient(
        [turn(text="Пока думаю"), turn(text="Ещё думаю"), turn(text="И ещё")]
    )
    with pytest.raises(PipelineError, match="не вызвал submit"):
        await _runner(client, task=_agent_input(mode=RunMode.ANALYZE)).run()
    assert len(client.calls) == 2
    nudges = [
        message
        for message in client.calls[-1]["messages"]  # type: ignore[union-attr]
        if message.role == "user" and "без вызова инструмента" in message.text
    ]
    assert nudges


# ---------- бюджет, лимит ходов, отмена ----------


@pytest.mark.asyncio
async def test_agent_stops_on_token_budget_without_raising_pipeline_error() -> None:
    client = RecordedToolClient(
        [turn(use("list_sources", {})) for _ in range(6)], usage=(50, 10, 0, 0)
    )
    runner = _runner(client, task=_agent_input(mode=RunMode.ANALYZE))
    with (
        run_budget(Budget(tokens=100)),
        track_run_usage(),
        pytest.raises(BudgetReachedError, match="токенов"),
    ):
        await runner.run()
    assert len(client.calls) == 2  # третий ход уже за бюджетом


@pytest.mark.asyncio
async def test_agent_stops_on_step_limit() -> None:
    client = RecordedToolClient([turn(use("list_sources", {})) for _ in range(6)])
    with pytest.raises(BudgetReachedError, match="Лимит ходов агента"):
        await _runner(client, task=_agent_input(max_steps=3)).run()
    assert len(client.calls) == 3


@pytest.mark.asyncio
async def test_agent_counts_spent_steps_after_restart() -> None:
    client = RecordedToolClient([turn(use("list_sources", {})) for _ in range(3)])
    with pytest.raises(BudgetReachedError, match="уже израсходован"):
        await _runner(client, task=_agent_input(max_steps=3, steps_spent=3)).run()
    assert client.calls == []


@pytest.mark.asyncio
async def test_agent_cancellation_interrupts_the_current_request() -> None:
    entered = asyncio.Event()

    class BlockingClient(RecordedToolClient):
        async def complete_with_tools(self, *args: Any, **kwargs: Any) -> ToolTurn:
            entered.set()
            await asyncio.sleep(3600)
            raise AssertionError("недостижимо")  # pragma: no cover

    runner = _runner(BlockingClient([]), task=_agent_input(mode=RunMode.ANALYZE))
    task = asyncio.create_task(runner.run())
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# ---------- сервис: прогон, журнал, восстановление ----------


class _LintTools:
    """Подмена runtime bpmn-tools: принятый submit уже валиден, layout не нужен.

    Настоящий Node-сервис строит DI; в этих тестах проверяется механика агентного режима и
    публикации версии, а не раскладка (её проверяет `node_url` в `test_graph_runtime`).
    """

    quality = "full"

    async def layout(self, xml: str) -> str:
        return xml

    async def lint(self, xml: str) -> list[Any]:
        return []


class _HoldSpawner:
    """Прогон принят, но не выполняется: так выглядит процесс, остановленный до старта."""

    def spawn(self, coro: Any, *, name: str) -> None:
        coro.close()

    async def cancel(self, *, name: str) -> bool:
        return False

    async def shutdown(self) -> None:
        return None


def _pipeline(turns: list[ToolTurn], *, usage: tuple[int, int, int, int] | None = None):
    client = RecordedToolClient(turns, usage=usage)
    return (
        LlmPipeline(
            client,
            provider="anthropic",
            model="claude-opus-5-5",
            capabilities=CAPABILITIES,
            json_max_tokens=8_192,
            context_budget_chars=120_000,
            effort="medium",
        ),
        client,
    )


def _runs(container: Container, pipeline: Any, spawner: Any, *, max_steps: int = 8) -> RunService:
    resolver = ModelResolver(
        container.repos,
        server_pipeline=pipeline,
        runtime=Runtime(),
        agent_enabled=True,
        agent_max_steps=max_steps,
        server_max_effort="max",
    )
    return RunService(
        container.repos,
        resolver=resolver,
        bpmn_tools=_LintTools(),  # type: ignore[arg-type]
        events=InMemoryRunEventBus(),
        spawner=spawner,
        runtime=Runtime(),
        max_concurrent=2,
        agent_limits=AgentLimits(max_steps=max_steps),
    )


async def _project(container: Container) -> tuple[UUID, UUID]:
    view = await container.projects.create(title="Проверка заявки", description=None)
    await container.sources.create_text(
        view.project.id,
        content=TEXT,
        title="Регламент",
        kind=SourceKind.TEXT,
        duration_sec=None,
    )
    sources = await container.repos.sources.list_by_project(view.project.id)
    return view.project.id, sources[0].id


def _simple_ir(source_id: UUID) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "title": "Проверка заявки",
        "lanes": [
            {
                "id": "Operator",
                "name": "Оператор",
                "source": {"source_id": str(source_id), "quote": "Оператор"},
            }
        ],
        "nodes": [
            {"id": "Start", "type": "start", "name": "Заявка получена", "lane": "Operator"},
            {
                "id": "Check",
                "type": "task",
                "name": "Проверить заявку",
                "lane": "Operator",
                "source": {"source_id": str(source_id), "quote": "проверяет заявку"},
            },
            {"id": "End", "type": "end", "name": "Решение принято", "lane": "Operator"},
        ],
        "flows": [
            {"id": "F1", "source_id": "Start", "target_id": "Check"},
            {"id": "F2", "source_id": "Check", "target_id": "End"},
        ],
    }


async def _wait(runs: RunService, run_id: UUID, status: RunStatus) -> Run:
    for _ in range(500):
        run = await runs.get(run_id)
        if run.status is status:
            return run
        if run.status in {RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.SUCCEEDED}:
            raise AssertionError(f"Прогон завершился статусом {run.status}: {run.error}")
        await asyncio.sleep(0.01)
    raise AssertionError(f"Прогон не перешёл в {status}")


@pytest.mark.asyncio
async def test_agent_run_through_service_builds_version_and_journal() -> None:
    container = build_container(Settings(mock_delay_scale=0, seed_demo_data=False))
    project_id, source_id = await _project(container)
    question = {
        **QUESTION,
        "quotes": [{"source_id": str(source_id), "quote": "проверяет заявку"}],
    }
    ir = _simple_ir(source_id)
    pipeline, client = _pipeline(
        [
            turn(use("list_sources", {})),
            turn(use("read_source", {"source_id": str(source_id), "from": 0, "limit": 80})),
            turn(use("submit", {"questions": [question], "ir": ir})),
        ],
        usage=(1_000, 200, 0, 0),
    )
    spawner = AsyncioTaskSpawner()
    runs = _runs(container, pipeline, spawner)
    run = await runs.start(
        project_id,
        mode=RunMode.BUILD,
        created_by=None,
        profile=RunProfile(mode="agent", max_steps=6),
    )
    await spawner.wait_idle()
    saved = await runs.get(run.id)
    assert saved.status is RunStatus.SUCCEEDED, saved.error
    assert saved.version_id is not None
    assert saved.summary is not None
    assert saved.summary.new == 1
    assert len(client.calls) == 3

    state = recorded_state(saved)
    assert state is not None
    assert state["submitted"] is True
    assert state["version"] == AGENT_PROMPT_VERSION
    assert state["steps"] == 3
    assert [item["tool"] for item in state["tools"]] == [
        "list_sources",
        "read_source",
        "submit",
    ]
    snapshot = json.dumps(state, ensure_ascii=False)
    assert TEXT not in snapshot  # тексты источников в журнал не копируются
    assert all(len(item["arguments_sha256"]) == 64 for item in state["tools"])

    calls = await container.repos.llm_calls.list_by_run(run.id)
    agent_calls = sorted(
        (call for call in calls if call.stage == "agent"),
        key=lambda call: call.request["step"],
    )
    assert len(agent_calls) == 3
    assert agent_calls[0].tokens_in == 1_000
    assert agent_calls[0].cost_usd is not None
    assert agent_calls[0].model == "claude-opus-5-5"
    request = json.dumps(agent_calls[0].request, ensure_ascii=False)
    assert "list_sources" in request
    assert "sha256" not in request or agent_calls[0].request["tools"][0]["arguments_sha256"]
    assert TEXT not in request

    # Схема опубликована обычными этапами прогона: версия и XML реальные.
    versions = await container.repos.versions.list_by_project(project_id)
    assert len(versions) == 1
    assert "<bpmn:definitions" in versions[0].xml


@pytest.mark.asyncio
async def test_agent_recovery_reuses_submitted_result_without_model_calls() -> None:
    container = build_container(Settings(mock_delay_scale=0, seed_demo_data=False))
    project_id, source_id = await _project(container)
    ir = _simple_ir(source_id)
    question = {
        **QUESTION,
        "quotes": [{"source_id": str(source_id), "quote": "проверяет заявку"}],
    }
    pipeline, _ = _pipeline(
        [turn(use("submit", {"questions": [question], "ir": ir}))],
        usage=(100, 20, 0, 0),
    )
    spawner = AsyncioTaskSpawner()
    runs = _runs(container, pipeline, spawner)
    run = await runs.start(
        project_id,
        mode=RunMode.BUILD,
        created_by=None,
        profile=RunProfile(mode="agent", max_steps=4),
    )
    await spawner.wait_idle()
    saved = await runs.get(run.id)
    assert saved.status is RunStatus.SUCCEEDED, saved.error
    assert saved.ir is not None
    submitted = saved.ir["execution"]["agent"]

    # Рестарт: версия не успела опубликоваться, но submit сдан. Модель больше не зовём.
    container.repos.versions._items.clear()  # type: ignore[attr-defined]
    saved.status = RunStatus.QUEUED
    saved.version_id = None
    saved.finished_at = None
    saved.stage = None
    saved.progress = 0.0
    await container.repos.runs.update(saved)

    empty_pipeline, empty_client = _pipeline([])
    restart_spawner = AsyncioTaskSpawner()
    restarted = _runs(container, empty_pipeline, restart_spawner)
    restarted.resume(run.id)
    await restart_spawner.wait_idle()
    final = await restarted.get(run.id)
    assert final.status is RunStatus.SUCCEEDED, final.error
    assert final.version_id is not None
    assert empty_client.calls == []  # ни одного платного запроса
    restored = final.ir["execution"]["agent"]  # type: ignore[index]
    assert restored["submitted"] is True
    assert restored["steps"] == submitted["steps"]
    assert restored["tools"] == submitted["tools"]
    agent_calls = [
        call
        for call in await container.repos.llm_calls.list_by_run(run.id)
        if call.stage == "agent"
    ]
    assert len(agent_calls) == 1  # новый журнал не появился


@pytest.mark.asyncio
async def test_unfinished_agent_run_continues_with_spent_steps_after_restart() -> None:
    container = build_container(Settings(mock_delay_scale=0, seed_demo_data=False))
    project_id, source_id = await _project(container)
    pipeline, _ = _pipeline([], usage=(100, 20, 0, 0))
    runs = _runs(container, pipeline, _HoldSpawner(), max_steps=4)
    run = await runs.start(
        project_id,
        mode=RunMode.ANALYZE,
        created_by=None,
        profile=RunProfile(mode="agent", max_steps=4),
    )
    saved = await runs.get(run.id)
    assert saved.ir is not None
    execution = dict(saved.ir["execution"])
    execution["agent"] = started_record(3, [{"call": 1, "tool": "list_sources"}])
    saved.ir = {**saved.ir, "execution": execution}
    await container.repos.runs.update(saved)

    # Остался один ход: модель сдаёт вопросы и прогон продолжается, а не начинается заново.
    question = {
        **QUESTION,
        "quotes": [{"source_id": str(source_id), "quote": "проверяет заявку"}],
    }
    next_pipeline, client = _pipeline(
        [turn(use("submit", {"questions": [question]}))], usage=(10, 2, 0, 0)
    )
    spawner = AsyncioTaskSpawner()
    restarted = _runs(container, next_pipeline, spawner, max_steps=4)
    restarted.resume(run.id)
    await spawner.wait_idle()
    final = await restarted.get(run.id)
    assert final.status is RunStatus.SUCCEEDED, final.error
    assert len(client.calls) == 1
    state = recorded_state(final)
    assert state is not None
    assert state["steps"] == 4


@pytest.mark.asyncio
async def test_agent_step_limit_waits_with_technical_question() -> None:
    container = build_container(Settings(mock_delay_scale=0, seed_demo_data=False))
    project_id, _ = await _project(container)
    pipeline, _ = _pipeline([turn(use("list_sources", {})) for _ in range(4)], usage=(10, 2, 0, 0))
    spawner = AsyncioTaskSpawner()
    runs = _runs(container, pipeline, spawner, max_steps=2)
    run = await runs.start(
        project_id,
        mode=RunMode.ANALYZE,
        created_by=None,
        profile=RunProfile(mode="agent", max_steps=2),
    )
    await spawner.wait_idle()
    waiting = await runs.get(run.id)
    assert waiting.status is RunStatus.WAITING
    assert waiting.error is None
    questions = await container.repos.questions.list_by_project(project_id)
    technical = [item for item in questions if item.category is QuestionCategory.TECHNICAL]
    assert len(technical) == 1
    assert technical[0].kind is TechnicalQuestionKind.BUDGET_REACHED
    assert "Лимит ходов" in technical[0].text


# ---------- API и проверка профиля ----------


def _api_container(**overrides: Any) -> Container:
    values: dict[str, Any] = {
        "mock_delay_scale": 0,
        "seed_demo_data": False,
        "app_env": "test",
        "auth_enabled": False,
        "rate_limit_enabled": False,
        "llm_provider": "mock",
        "stt_provider": "mock",
        "deepseek_api_key": None,
        "deepgram_api_key": None,
    }
    values.update(overrides)
    return build_container(Settings(**values))


def test_agent_mode_is_disabled_by_default(settings: Settings) -> None:
    container = _api_container()
    view = asyncio.run(container.projects.create(title="Процесс", description=None))
    asyncio.run(
        container.sources.create_text(
            view.project.id,
            content=TEXT,
            title=None,
            kind=SourceKind.TEXT,
            duration_sec=None,
        )
    )
    with TestClient(create_app(container.settings, container=container)) as client:
        response = client.post(
            f"/api/v1/projects/{view.project.id}/runs",
            json={"mode": "analyze", "profile": {"mode": "agent"}},
        )
    assert response.status_code == 422
    assert "выключен" in response.json()["detail"]


def test_agent_mode_requires_model_with_tools() -> None:
    container = _api_container(llm_agent_mode=True)
    view = asyncio.run(container.projects.create(title="Процесс", description=None))
    asyncio.run(
        container.sources.create_text(
            view.project.id,
            content=TEXT,
            title=None,
            kind=SourceKind.TEXT,
            duration_sec=None,
        )
    )
    with TestClient(create_app(container.settings, container=container)) as client:
        response = client.post(
            f"/api/v1/projects/{view.project.id}/runs",
            json={"mode": "analyze", "profile": {"mode": "agent"}},
        )
    assert response.status_code == 422
    assert "не поддерживает инструменты" in response.json()["detail"]


def test_max_steps_requires_agent_mode() -> None:
    pipeline, _ = _pipeline([])
    resolver = ModelResolver(None, server_pipeline=pipeline, agent_enabled=True, agent_max_steps=8)
    with pytest.raises(InvalidInputError, match="только для агентного режима"):
        asyncio.run(resolver.resolve(None, profile=RunProfile(max_steps=3)))


def test_max_steps_cannot_exceed_server_ceiling() -> None:
    pipeline, _ = _pipeline([])
    resolver = ModelResolver(None, server_pipeline=pipeline, agent_enabled=True, agent_max_steps=4)
    with pytest.raises(InvalidInputError, match="не больше 4"):
        asyncio.run(resolver.resolve(None, profile=RunProfile(mode="agent", max_steps=10)))


def test_agent_mode_checked_against_capabilities() -> None:
    pipeline, _ = _pipeline([])
    resolver = ModelResolver(None, server_pipeline=pipeline, agent_enabled=False)
    with pytest.raises(InvalidInputError, match="выключен"):
        asyncio.run(resolver.resolve(None, profile=RunProfile(mode="agent")))

    plain = LlmPipeline(
        RecordedToolClient([]),
        provider="anthropic",
        model="claude-haiku-4-5",
        capabilities=replace(CAPABILITIES, tools=False),
        json_max_tokens=8_192,
    )
    resolver = ModelResolver(None, server_pipeline=plain, agent_enabled=True)
    with pytest.raises(InvalidInputError, match="не поддерживает инструменты"):
        asyncio.run(resolver.resolve(None, profile=RunProfile(mode="agent")))


# ---------- полнотекстовый поиск: in-memory ----------


@pytest.mark.asyncio
async def test_memory_source_search_filters_and_ranks() -> None:
    store = InMemoryStore()
    repos = store.repositories()
    project_id = uuid4()
    now = datetime(2026, 11, 4, tzinfo=UTC)
    await repos.projects.add(
        Project(id=project_id, title="Проект", description=None, created_at=now, updated_at=now)
    )

    def source(title: str, content: str, *, active: bool = True) -> Source:
        return Source(
            id=uuid4(),
            project_id=project_id,
            kind=SourceKind.TEXT,
            title=title,
            content=content,
            status=SourceStatus.READY,
            active=active,
            created_at=now,
        )

    visible = source("Регламент", "Оператор проверяет заявку.")
    duplicate = source("Памятка", "Заявка проверяется оператором.")
    inactive = source("Старое", "Заявка устарела.", active=False)
    await repos.sources.add(visible)
    await repos.sources.add(duplicate)
    await repos.sources.add(inactive)

    hits = await repos.sources.search(project_id, "оператор", limit=5)
    assert {hit.source_id for hit in hits} == {visible.id, duplicate.id}
    assert all(hit.snippet for hit in hits)
    assert len(await repos.sources.search(project_id, "оператор", limit=1)) == 1
    assert await repos.sources.search(project_id, "энергосбыт", limit=5) == []
    assert await repos.sources.search(project_id, "", limit=5) == []
    assert await repos.sources.search(project_id, "оператор", limit=0) == []


# ---------- профиль и оценка агентного прогона ----------


def test_run_profile_roundtrip_keeps_agent_mode() -> None:
    profile = RunProfile(mode="agent", max_steps=7, effort="high")
    restored = RunProfile.from_json(json.loads(json.dumps(profile.to_json())))
    assert restored == profile
    assert RunProfile.from_json({"mode": "evil", "max_steps": -1}) == RunProfile()


def test_agent_estimate_counts_steps_instead_of_pipeline_stages() -> None:
    estimate = estimate_run(
        EstimateInput(
            mode=RunMode.BUILD,
            source_chars=40_000,
            budget_chars=120_000,
            chunk_chars=24_000,
            semantic_review=True,
            capabilities=CAPABILITIES,
            agent_mode=True,
            agent_max_steps=10,
        )
    )
    assert [stage.stage for stage in estimate.breakdown] == ["agent"]
    assert estimate.calls.max == 10
    assert estimate.calls.min == 2
    assert estimate.cost is not None
    assert any("Агентный режим" in note for note in estimate.notes)


@pytest.mark.asyncio
async def test_agent_run_can_be_cancelled_during_a_model_request() -> None:
    container = build_container(Settings(mock_delay_scale=0, seed_demo_data=False))
    project_id, _ = await _project(container)
    entered = asyncio.Event()

    class BlockingClient(RecordedToolClient):
        async def complete_with_tools(self, *args: Any, **kwargs: Any) -> ToolTurn:
            entered.set()
            await asyncio.sleep(3600)
            raise AssertionError("недостижимо")  # pragma: no cover

    pipeline = LlmPipeline(
        BlockingClient([]),
        provider="anthropic",
        model="claude-opus-5-5",
        capabilities=CAPABILITIES,
        json_max_tokens=8_192,
        context_budget_chars=120_000,
        effort="medium",
    )
    spawner = AsyncioTaskSpawner()
    runs = _runs(container, pipeline, spawner)
    run = await runs.start(
        project_id,
        mode=RunMode.ANALYZE,
        created_by=None,
        profile=RunProfile(mode="agent"),
    )
    await asyncio.wait_for(entered.wait(), timeout=1)
    cancelled = await runs.cancel(run.id)
    await spawner.wait_idle()
    assert cancelled.status is RunStatus.CANCELLED
    assert cancelled.error == "Прогон отменён участником"
