"""Исправления ревью волны 2: промпты, бюджет, отмена, висящие техвопросы.

Проверяются пункты MAJOR 1–3 и 5, плюс minors: отметка ключа при остановке по бюджету,
полнота RunCost, ручное сохранение при `waiting`, учёт потраченного после рестарта.
"""

import asyncio
import json
from datetime import UTC, date, datetime
from typing import cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Table

from app.config import Settings
from app.container import Container, build_container
from app.domain.analysis import AnalysisResult, ContextSource, RunContext
from app.domain.bpmn.ir import GraphIR
from app.domain.models import (
    LlmCall,
    Question,
    QuestionActionKind,
    QuestionCategory,
    QuestionKind,
    QuestionStatus,
    Run,
    RunMode,
    RunStatus,
    Severity,
    SourceKind,
    TechnicalQuestionKind,
)
from app.fixtures import read_bpmn
from app.fixtures.playbook import PLAYBOOK
from app.infra.db_models import RunRow
from app.infra.seed import DEMO_PROJECT_ID
from app.llm.base import BudgetReachedError, record_usage
from app.llm.capabilities import Budget, ModelCapabilities, RunProfile
from app.llm.mock import MockPipeline
from app.llm.semantic_review import review_semantics
from app.services.errors import ConflictError, InvalidInputError
from tests.conftest import API
from tests.llm_helpers import ScriptedPipeline
from tests.test_graph_ir import graph_case
from tests.test_technical_questions import (
    CAPABILITIES,
    BudgetThenMock,
    _container_with_budget,
    _wait_http,
    _wait_status,
)

# ---------- вспомогательные пайплайны ----------


class CapturingMock:
    """Mock-пайплайн, запоминающий контекст анализа и сборки (для проверки промптов)."""

    provider = "anthropic"
    model_name = "claude-opus-5-5"
    capabilities = CAPABILITIES

    def __init__(self) -> None:
        self._mock = MockPipeline(playbook=PLAYBOOK, read_bpmn=read_bpmn)
        self.analyze_context: RunContext | None = None
        self.structure_context: RunContext | None = None

    async def analyze(self, context: RunContext) -> AnalysisResult:
        self.analyze_context = context
        return await self._mock.analyze(context)

    async def structure(self, context: RunContext, analysis: AnalysisResult):
        self.structure_context = context
        return await self._mock.structure(context, analysis)

    async def count_tokens(self, system: str, user: str) -> int:
        return max((len(system) + len(user)) // 2, 1)

    async def aclose(self) -> None:
        await self._mock.aclose()


class SlowMock:
    """Пайплайн, «зависающий» в запросе: прогон отменяется во время вызова модели."""

    provider = "anthropic"
    model_name = "claude-opus-5-5"
    capabilities = CAPABILITIES

    def __init__(self) -> None:
        self._mock = MockPipeline(playbook=PLAYBOOK, read_bpmn=read_bpmn)
        self.started = asyncio.Event()

    async def analyze(self, context: RunContext) -> AnalysisResult:
        record_usage(tokens_in=17, tokens_out=3, cache_read=4, cache_write=2)
        self.started.set()
        await asyncio.sleep(10)
        return await self._mock.analyze(context)

    async def structure(self, context: RunContext, analysis: AnalysisResult):
        return await self._mock.structure(context, analysis)

    async def aclose(self) -> None:
        await self._mock.aclose()


class UsageThenBudgetMock(BudgetThenMock):
    """Первый запрос тратит токены и упирается в бюджет, дальше работает mock."""

    async def analyze(self, context: RunContext) -> AnalysisResult:
        self.analyze_calls += 1
        if self.analyze_calls == 1:
            record_usage(tokens_in=50, tokens_out=10)
            raise BudgetReachedError("Бюджет исчерпан", budget=Budget(tokens=10))
        return await self._mock.analyze(context)


class NoPricesBudgetMock(BudgetThenMock):
    """Модель без цен: бюджет в деньгах проверить нельзя."""

    capabilities = ModelCapabilities(chars_per_token=2.0)


class ChatCapture(ScriptedPipeline):
    """Пайплайн помощника: запоминает переданный контекст чата."""

    def __init__(self) -> None:
        super().__init__(
            provider="anthropic",
            model="claude-opus-5-5",
            capabilities=CAPABILITIES,
            complete=lambda _s, _u: "{}",
        )
        # Пайплайн профиля — мелкая копия (`LlmPipeline._copy`), поэтому копим в общий список.
        self.chats: list[dict[str, object]] = []

    async def chat(self, **kwargs: object) -> str:
        self.chats.append(kwargs)
        return "Ответ помощника"


def test_active_run_index_includes_waiting() -> None:
    table = cast(Table, RunRow.__table__)
    where = str(
        next(
            index for index in table.indexes if index.name == "uq_runs_active_project"
        ).dialect_options["postgresql"]["where"]
    )
    assert "waiting" in where


# ---------- 1. технические вопросы не попадают в промпты ----------


@pytest.mark.asyncio
async def test_structure_prompt_and_llm_calls_exclude_technical_questions(
    settings: Settings,
) -> None:
    container = build_container(settings)
    pipeline = CapturingMock()
    container.runs._resolver.server_pipeline = pipeline
    try:
        technical = await container.technical_questions.create(
            DEMO_PROJECT_ID,
            TechnicalQuestionKind.QUOTA_EXHAUSTED,
            "Квота распознавания закончилась.",
            blocking=False,
        )
        run = await container.runs.start(DEMO_PROJECT_ID, mode=RunMode.BUILD, created_by=None)
        await _wait_status(container, run.id, RunStatus.SUCCEEDED)
        assert pipeline.structure_context is not None
        assert all(not q.is_technical for q in pipeline.structure_context.questions)
        assert technical.id not in {q.id for q in pipeline.structure_context.questions}
        # Коды бизнес- и техвопросов не пересекаются: технический занимает свой номер.
        project_questions = await container.repos.questions.list_by_project(DEMO_PROJECT_ID)
        codes = [question.code for question in project_questions]
        assert len(codes) == len(set(codes))
        # В журнале вызовов у запросов анализа и сборки тоже нет техвопроса.
        calls = await container.repos.llm_calls.list_by_run(run.id)
        assert calls
        for call in calls:
            context = (call.request or {}).get("context") or {}
            codes = {item.get("code") for item in context.get("questions", [])}
            assert technical.code not in codes
    finally:
        await container.spawner.shutdown()


@pytest.mark.asyncio
async def test_semantic_review_prompt_excludes_technical_questions() -> None:
    graph = GraphIR.model_validate(graph_case())
    now = datetime.now(UTC)
    business = Question(
        id=uuid4(),
        project_id=uuid4(),
        code="Q-1",
        kind=QuestionKind.MISSING_ACTOR,
        severity=Severity.MAJOR,
        status=QuestionStatus.OPEN,
        text="Кто согласует?",
        assumption="Согласует руководитель",
        created_at=now,
        updated_at=now,
    )
    technical = Question(
        id=uuid4(),
        project_id=business.project_id,
        code="Q-2",
        kind=TechnicalQuestionKind.QUOTA_EXHAUSTED,
        severity=Severity.MAJOR,
        status=QuestionStatus.OPEN,
        text="Квота закончилась",
        assumption="",
        created_at=now,
        updated_at=now,
        category=QuestionCategory.TECHNICAL,
    )
    context = RunContext(
        project_id=business.project_id,
        project_title="Процесс",
        sources=[
            ContextSource(
                id=uuid4(),
                kind=SourceKind.TEXT,
                title="Регламент",
                content="Оператор согласует заявку.",
                created_at=now,
            )
        ],
        questions=[business, technical],
        analysis_budget_chars=10_000,
        chunk_chars=10_000,
    )
    prompts: list[str] = []

    async def complete(_system: str, prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps({"issues": []})

    errors = await review_semantics(graph, context, complete)
    assert errors == []
    assert prompts
    for prompt in prompts:
        assert "Q-2" not in prompt
        assert "Q-1" in prompt


@pytest.mark.asyncio
async def test_assistant_chat_excludes_technical_questions(settings: Settings) -> None:
    container = build_container(settings)
    pipeline = ChatCapture()
    container.assistant._resolver.server_pipeline = pipeline
    try:
        technical = await container.technical_questions.create(
            DEMO_PROJECT_ID,
            TechnicalQuestionKind.QUOTA_EXHAUSTED,
            "Квота распознавания закончилась.",
            blocking=False,
        )
        await container.assistant.reply(
            DEMO_PROJECT_ID, message="Что дальше?", diagram_xml="", history=[]
        )
        assert pipeline.chats
        questions = pipeline.chats[-1]["questions"]
        assert isinstance(questions, list)
        assert all(item.get("code") != technical.code for item in questions)
    finally:
        await container.spawner.shutdown()


# ---------- 2. бюджет: объединение, проверки, resume ----------


@pytest.mark.asyncio
async def test_resume_without_raise_is_refused(settings: Settings) -> None:
    container = build_container(settings)
    pipeline = UsageThenBudgetMock()
    container.runs._resolver.server_pipeline = pipeline
    try:
        run = await container.runs.start(
            DEMO_PROJECT_ID,
            mode=RunMode.ANALYZE,
            created_by=None,
            profile=RunProfile(budget=Budget(tokens=10)),
        )
        await _wait_status(container, run.id, RunStatus.WAITING)
        questions = await container.repos.questions.list_by_project(DEMO_PROJECT_ID)
        question = next(q for q in questions if q.is_technical)
        # Повторная остановка по тому же прогону не создаёт дубль вопроса.
        duplicate = await container.technical_questions.create(
            DEMO_PROJECT_ID,
            TechnicalQuestionKind.BUDGET_REACHED,
            "Бюджет исчерпан повторно",
            run_id=run.id,
        )
        assert duplicate.id == question.id

        # Продолжение без поднятия бюджета сразу вернулось бы в waiting — это 409, а не цикл.
        with pytest.raises(ConflictError, match="Бюджет прогона исчерпан"):
            await container.runs.resume_waiting(run.id)
        stored = await container.repos.questions.get(question.id)
        assert stored is not None
        assert stored.status is QuestionStatus.OPEN  # вопрос не закрыт неудачным resume
        assert (await container.runs.get(run.id)).status is RunStatus.WAITING

        # После поднятия бюджета продолжение разрешено, вопрос становится неактуальным.
        await container.runs.raise_budget(run.id, Budget(tokens=500))
        resumed = await container.runs.resume_waiting(run.id)
        assert resumed.status is RunStatus.QUEUED
        finished = await _wait_status(container, run.id, RunStatus.SUCCEEDED)
        assert finished.status is RunStatus.SUCCEEDED
        assert pipeline.analyze_calls == 2
        closed = await container.repos.questions.get(question.id)
        assert closed is not None
        assert closed.status in {QuestionStatus.OBSOLETE, QuestionStatus.IGNORED}
    finally:
        await container.spawner.shutdown()


@pytest.mark.asyncio
async def test_raise_budget_merges_monotonically_and_keeps_tokens(
    settings: Settings,
) -> None:
    container, _ = _container_with_budget(settings)
    try:
        run = await container.runs.start(
            DEMO_PROJECT_ID,
            mode=RunMode.ANALYZE,
            created_by=None,
            profile=RunProfile(budget=Budget(tokens=10)),
        )
        await _wait_status(container, run.id, RunStatus.WAITING)
        # Задаём только стоимость: лимит токенов не должен потеряться.
        await container.runs.raise_budget(run.id, Budget(cost_usd=7.5))
        stored = await container.repos.runs.get(run.id)
        assert stored is not None
        assert stored.ir is not None
        budget = stored.ir["execution"]["profile"]["budget"]
        assert budget == {"tokens": 10, "cost_usd": 7.5}
    finally:
        await container.spawner.shutdown()


@pytest.mark.asyncio
async def test_raise_budget_requires_prices_for_money(settings: Settings) -> None:
    container = build_container(settings)
    container.runs._resolver.server_pipeline = NoPricesBudgetMock()
    try:
        run = await container.runs.start(
            DEMO_PROJECT_ID,
            mode=RunMode.ANALYZE,
            created_by=None,
            profile=RunProfile(budget=Budget(tokens=10)),
        )
        await _wait_status(container, run.id, RunStatus.WAITING)
        with pytest.raises(InvalidInputError, match="цен"):
            await container.runs.raise_budget(run.id, Budget(cost_usd=5))
    finally:
        await container.spawner.shutdown()


@pytest.mark.asyncio
async def test_raise_budget_must_exceed_already_spent(settings: Settings) -> None:
    container = build_container(settings)
    container.runs._resolver.server_pipeline = UsageThenBudgetMock()
    try:
        run = await container.runs.start(
            DEMO_PROJECT_ID,
            mode=RunMode.ANALYZE,
            created_by=None,
            profile=RunProfile(budget=Budget(tokens=10)),
        )
        await _wait_status(container, run.id, RunStatus.WAITING)
        # Потрачено 60 токенов: граница ниже потраченного означала бы остановку сразу.
        with pytest.raises(InvalidInputError, match="выше уже потраченного"):
            await container.runs.raise_budget(run.id, Budget(tokens=15))
        await container.runs.raise_budget(run.id, Budget(tokens=500))
        await container.runs.resume_waiting(run.id)
        finished = await _wait_status(container, run.id, RunStatus.SUCCEEDED)
        assert finished.status is RunStatus.SUCCEEDED
    finally:
        await container.spawner.shutdown()


@pytest.mark.asyncio
async def test_budget_stop_does_not_mark_key_fatal(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    container, _ = _container_with_budget(settings)
    marks: list[str | None] = []

    async def mark(_credential_id, error):
        marks.append(error)

    monkeypatch.setattr(container.runs._resolver, "mark", mark)
    try:
        run = await container.runs.start(
            DEMO_PROJECT_ID,
            mode=RunMode.ANALYZE,
            created_by=None,
            profile=RunProfile(budget=Budget(tokens=10)),
        )
        await _wait_status(container, run.id, RunStatus.WAITING)
        # Остановка по бюджету — не ошибка ключа: текст ошибки в last_error не пишется.
        assert marks
        assert all(error is None for error in marks)
    finally:
        await container.spawner.shutdown()


# ---------- 3. прерванный шаг и учёт потраченного ----------


@pytest.mark.asyncio
async def test_cancelled_model_call_is_recorded(settings: Settings) -> None:
    container = build_container(settings)
    pipeline = SlowMock()
    container.runs._resolver.server_pipeline = pipeline
    try:
        run = await container.runs.start(DEMO_PROJECT_ID, mode=RunMode.ANALYZE, created_by=None)
        await asyncio.wait_for(pipeline.started.wait(), timeout=5)
        await container.runs.cancel(run.id)
        calls = await container.repos.llm_calls.list_by_run(run.id)
        recorded = [call for call in calls if call.stage == "analyze"]
        assert recorded, "прерванный вызов модели должен попасть в llm_calls"
        call = recorded[0]
        assert (call.tokens_in, call.tokens_out) == (17, 3)
        assert (call.cache_read_tokens, call.cache_write_tokens) == (4, 2)
        assert "прерван" in str(call.response.get("error", "")).lower()
        # Потраченное на прерванном шаге входит в счёт бюджета следующего исполнения.
        spent = await container.runs._spent_usage(run.id)
        assert (spent.tokens_in, spent.tokens_out) == (17, 3)
    finally:
        await container.spawner.shutdown()


@pytest.mark.asyncio
async def test_recovered_run_counts_spent_in_budget(settings: Settings) -> None:
    container = build_container(settings)
    pipeline = ScriptedPipeline(
        provider="anthropic",
        model="claude-opus-5-5",
        capabilities=CAPABILITIES,
        complete=lambda _s, _u: "{}",
    )
    container.runs._resolver.server_pipeline = pipeline
    try:
        now = datetime.now(UTC)
        run = Run(
            id=uuid4(),
            project_id=DEMO_PROJECT_ID,
            mode=RunMode.ANALYZE,
            status=RunStatus.QUEUED,
            started_at=now,
            model="claude-opus-5-5",
            ir={
                "execution": {
                    "provider": "anthropic",
                    "profile": {
                        "effort": None,
                        "semantic_review": None,
                        "budget": {"tokens": 10, "cost_usd": None},
                    },
                }
            },
        )
        await container.repos.runs.add(run)
        seeded = LlmCall(
            id=uuid4(),
            run_id=run.id,
            stage="analyze",
            request={},
            response={},
            tokens_in=100,
            tokens_out=20,
            cost_usd=0.5,
            price_checked_on=date(2026, 10, 6),
        )
        await container.repos.llm_calls.add(seeded)
        container.runs.resume(run.id)
        waiting = await _wait_status(container, run.id, RunStatus.WAITING)
        assert waiting.status is RunStatus.WAITING
        # Бюджет проверен до запроса к провайдеру: новая строка — только нейтральная запись
        # об остановке без токенов, реальных оплаченных вызовов не было.
        calls = await container.repos.llm_calls.list_by_run(run.id)
        assert len(calls) == 2
        neutral = next(call for call in calls if call.id != seeded.id)
        assert neutral.tokens_in is None
        assert neutral.cost_usd is None
        assert "бюджет" in str(neutral.response.get("error", "")).lower()
    finally:
        await container.spawner.shutdown()


# ---------- 5. висящие техвопросы ----------


@pytest.mark.asyncio
async def test_cancel_waiting_run_obsoletes_questions(settings: Settings) -> None:
    container, _ = _container_with_budget(settings)
    try:
        run = await container.runs.start(
            DEMO_PROJECT_ID,
            mode=RunMode.ANALYZE,
            created_by=None,
            profile=RunProfile(budget=Budget(tokens=10)),
        )
        await _wait_status(container, run.id, RunStatus.WAITING)
        questions = await container.repos.questions.list_by_project(DEMO_PROJECT_ID)
        question = next(q for q in questions if q.is_technical)
        cancelled = await container.runs.cancel(run.id)
        assert cancelled.status is RunStatus.CANCELLED
        stored = await container.repos.questions.get(question.id)
        assert stored is not None
        assert stored.status is QuestionStatus.OBSOLETE
        # Проект освобождён: новый прогон разрешён.
        fresh = await container.runs.start(DEMO_PROJECT_ID, mode=RunMode.ANALYZE, created_by=None)
        assert fresh.status in {RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.SUCCEEDED}
    finally:
        await container.spawner.shutdown()


@pytest.mark.asyncio
async def test_continue_without_keeps_question_when_resume_fails(
    settings: Settings,
) -> None:
    """«Продолжить без этого» закрывает вопрос только после успешного продолжения."""
    container = build_container(settings)
    try:
        run = await container.runs.start(DEMO_PROJECT_ID, mode=RunMode.ANALYZE, created_by=None)
        await _wait_status(container, run.id, RunStatus.SUCCEEDED)
        question = await container.technical_questions.create(
            DEMO_PROJECT_ID,
            TechnicalQuestionKind.QUOTA_EXHAUSTED,
            "Квота распознавания закончилась.",
            run_id=run.id,
            blocking=False,
        )
        # Прогон уже завершён: продолжить нельзя, поэтому вопрос остаётся открытым.
        with pytest.raises(ConflictError):
            await container.technical_questions.apply_action(
                question.id, QuestionActionKind.CONTINUE_WITHOUT
            )
        stored = await container.repos.questions.get(question.id)
        assert stored is not None
        assert stored.status is QuestionStatus.OPEN
    finally:
        await container.spawner.shutdown()


# ---------- minor: ручное сохранение при waiting ----------


def test_manual_save_is_allowed_while_build_waits(client: TestClient, container: Container) -> None:
    container.runs._resolver.server_pipeline = BudgetThenMock()
    response = client.post(
        f"{API}/projects/{DEMO_PROJECT_ID}/runs",
        json={"mode": "build", "profile": {"budget": {"tokens": 10}}},
    )
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    _wait_http(client, run_id, "waiting")

    head = client.get(f"{API}/projects/{DEMO_PROJECT_ID}").json()["latest_version"]["id"]
    xml = client.get(f"{API}/versions/{head}").json()["xml"]
    changed = xml.replace("Провести выездной осмотр", "Осмотреть установку")
    assert changed != xml
    saved = client.put(
        f"{API}/projects/{DEMO_PROJECT_ID}/diagram",
        json={"xml": changed, "base_version_id": head},
    )
    assert saved.status_code == 201, saved.text
    assert saved.json()["origin"] == "manual"

    # Отмена ожидания освобождает проект и закрывает вопрос.
    cancelled = client.post(f"{API}/runs/{run_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


# ---------- API-инварианты ----------


def test_question_actions_merge_and_validation_over_http(
    client: TestClient, container: Container
) -> None:
    container.runs._resolver.server_pipeline = BudgetThenMock()
    started = client.post(
        f"{API}/projects/{DEMO_PROJECT_ID}/runs",
        json={"mode": "analyze", "profile": {"budget": {"tokens": 10}}},
    )
    run_id = started.json()["id"]
    _wait_http(client, run_id, "waiting")
    question = client.get(
        f"{API}/projects/{DEMO_PROJECT_ID}/questions", params={"category": "technical"}
    ).json()[0]

    # Бюджет не вырос — 422 до продолжения.
    rejected = client.post(
        f"{API}/questions/{question['id']}/actions",
        json={"action": "raise_budget", "budget": {"tokens": 10}},
    )
    assert rejected.status_code == 422
    assert "больше текущего" in rejected.json()["detail"]

    raised = client.post(
        f"{API}/questions/{question['id']}/actions",
        json={"action": "raise_budget", "budget": {"tokens": 500}},
    )
    assert raised.status_code == 200, raised.text
    _wait_http(client, run_id, "succeeded")
