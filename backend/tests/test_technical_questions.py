"""Технические вопросы, ожидание прогона и бюджет (RFC-0006 шаг 2, RFC-0005 шаг 5)."""

import asyncio
import time
from datetime import date
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.container import Container, build_container
from app.domain.models import (
    QuestionActionKind,
    QuestionCategory,
    QuestionStatus,
    Run,
    RunMode,
    RunStatus,
    TechnicalQuestionKind,
)
from app.domain.questions import default_actions
from app.domain.runs import ACTIVE_STATUSES
from app.fixtures import read_bpmn
from app.fixtures.playbook import PLAYBOOK
from app.infra.seed import DEMO_PROJECT_ID
from app.llm.base import BudgetReachedError
from app.llm.capabilities import Budget, ModelCapabilities, ModelPrices, RunProfile
from app.llm.mock import MockPipeline
from app.services.errors import ConflictError, InvalidInputError
from tests.conftest import API, add_text, create_project

PRICES = ModelPrices(
    input=4.0, output=20.0, cache_read=0.2, cache_write=5.0, checked_on=date(2026, 10, 6)
)
CAPABILITIES = ModelCapabilities(
    context_tokens=1_000_000,
    max_output_tokens=128_000,
    prices=PRICES,
    chars_per_token=2.0,
    known=True,
)


class BudgetThenMock:
    """Пайплайн-обёртка: первый вызов анализа упирается в бюджет, затем работает mock."""

    provider = "anthropic"
    model_name = "claude-opus-5-5"
    capabilities = CAPABILITIES

    def __init__(self) -> None:
        self._mock = MockPipeline(playbook=PLAYBOOK, read_bpmn=read_bpmn)
        self.analyze_calls = 0

    async def analyze(self, context):
        self.analyze_calls += 1
        if self.analyze_calls == 1:
            raise BudgetReachedError("Бюджет прогона 10 токенов исчерпан", budget=Budget(tokens=10))
        return await self._mock.analyze(context)

    async def structure(self, context, analysis):
        return await self._mock.structure(context, analysis)

    async def count_tokens(self, system: str, user: str) -> int:
        return max((len(system) + len(user)) // 2, 1)

    async def aclose(self) -> None:
        await self._mock.aclose()


def _container_with_budget(settings: Settings) -> tuple[Container, BudgetThenMock]:
    container = build_container(settings)
    pipeline = BudgetThenMock()
    container.runs._resolver.server_pipeline = pipeline
    return container, pipeline


async def _wait_status(container: Container, run_id: UUID, status: RunStatus) -> Run:
    for _ in range(500):
        run = await container.runs.get(run_id)
        if run.status is status:
            return run
        if run.status in {RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.SUCCEEDED}:
            raise AssertionError(f"Прогон завершился статусом {run.status}: {run.error}")
        await asyncio.sleep(0.01)
    raise AssertionError(f"Прогон не перешёл в {status}")


# ---------- домен ----------


def test_default_actions_follow_question_kind() -> None:
    budget = default_actions(TechnicalQuestionKind.BUDGET_REACHED)
    assert [item.kind for item in budget] == [
        QuestionActionKind.RAISE_BUDGET,
        QuestionActionKind.OPEN_SETTINGS,
    ]
    assert budget[0].label == "Поднять бюджет"
    quota = default_actions(TechnicalQuestionKind.QUOTA_EXHAUSTED)
    assert {item.kind for item in quota} == {
        QuestionActionKind.OPEN_SETTINGS,
        QuestionActionKind.RETRY,
        QuestionActionKind.CONTINUE_WITHOUT,
    }
    assert default_actions(TechnicalQuestionKind.INPUT_INCOMPLETE)[0].kind is (
        QuestionActionKind.CONTINUE_WITHOUT
    )


def test_waiting_status_is_active() -> None:
    assert RunStatus.WAITING in ACTIVE_STATUSES


# ---------- сервис и прогон ----------


@pytest.mark.asyncio
async def test_budget_stop_waits_with_technical_question(settings: Settings) -> None:
    container, pipeline = _container_with_budget(settings)
    try:
        run = await container.runs.start(
            DEMO_PROJECT_ID,
            mode=RunMode.ANALYZE,
            created_by=None,
            profile=RunProfile(budget=Budget(tokens=10)),
        )
        run = await _wait_status(container, run.id, RunStatus.WAITING)
        assert run.error is None

        questions = await container.repos.questions.list_by_project(DEMO_PROJECT_ID)
        technical = [q for q in questions if q.category is QuestionCategory.TECHNICAL]
        assert len(technical) == 1
        question = technical[0]
        assert question.kind is TechnicalQuestionKind.BUDGET_REACHED
        assert question.blocking is True
        assert question.run_id == run.id
        assert [item.kind for item in question.actions] == [
            QuestionActionKind.RAISE_BUDGET,
            QuestionActionKind.OPEN_SETTINGS,
        ]
        # Технический вопрос не попадает в бизнес-сводку и в контекст модели.
        assert question.code not in {q.code for q in questions if not q.is_technical}

        # Второй прогон по проекту, пока первый ждёт, начать нельзя.
        with pytest.raises(ConflictError, match="уже идёт"):
            await container.runs.start(DEMO_PROJECT_ID, mode=RunMode.BUILD, created_by=None)

        # Бюджет можно только поднять: запрошенное меньшее значение не поднимает границу.
        with pytest.raises(InvalidInputError, match="больше текущего"):
            await container.runs.raise_budget(run.id, Budget(tokens=5))

        # Действие «поднять бюджет» сохраняет новый бюджет и продолжает прогон.
        updated = await container.technical_questions.apply_action(
            question.id,
            QuestionActionKind.RAISE_BUDGET,
            budget=Budget(tokens=500),
        )
        assert updated.status is QuestionStatus.RESOLVED
        finished = await _wait_status(container, run.id, RunStatus.SUCCEEDED)
        assert finished.status is RunStatus.SUCCEEDED
        assert pipeline.analyze_calls == 2
        stored = await container.repos.runs.get(run.id)
        assert stored is not None
        assert stored.ir is not None
        assert stored.ir["execution"]["profile"]["budget"] == {
            "tokens": 500,
            "cost_usd": None,
        }
        # Успешный прогон не оставляет открытых технических вопросов.
        remaining = await container.repos.questions.list_by_project(DEMO_PROJECT_ID)
        assert remaining == [] or all(
            q.status is not QuestionStatus.OPEN for q in remaining if q.is_technical
        )
    finally:
        await container.spawner.shutdown()


@pytest.mark.asyncio
async def test_continue_without_closes_question_and_resumes(settings: Settings) -> None:
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
        # «Продолжить без этого» нет у бюджета, поэтому действие отклоняется.
        with pytest.raises(InvalidInputError, match="недоступно"):
            await container.technical_questions.apply_action(
                question.id, QuestionActionKind.CONTINUE_WITHOUT
            )
        # Повторное действие по закрытому вопросу — конфликт.
        await container.technical_questions.apply_action(
            question.id, QuestionActionKind.RAISE_BUDGET, budget=Budget(tokens=500)
        )
        await _wait_status(container, run.id, RunStatus.SUCCEEDED)
        with pytest.raises(ConflictError, match="закрыт"):
            await container.technical_questions.apply_action(
                question.id, QuestionActionKind.RAISE_BUDGET, budget=Budget(tokens=900)
            )
    finally:
        await container.spawner.shutdown()


@pytest.mark.asyncio
async def test_technical_question_create_and_actions_without_run(settings: Settings) -> None:
    container = build_container(settings)
    try:
        project_id = DEMO_PROJECT_ID
        question = await container.technical_questions.create(
            project_id,
            TechnicalQuestionKind.QUOTA_EXHAUSTED,
            "У распознавания речи закончилась квота: не расшифровано 46 из 80 минут.",
        )
        assert question.category is QuestionCategory.TECHNICAL
        assert question.blocking is True
        assert question.code.startswith("Q-")
        # Технический вопрос нельзя решить текстовым ответом.
        with pytest.raises(InvalidInputError, match="действием"):
            await container.questions.answer(question.id, text="Прочитайте сами")
        # «Повторить» без прогона не предлагается и недоступно, «продолжить без этого»
        # закрывает вопрос.
        assert QuestionActionKind.RETRY not in {item.kind for item in question.actions}
        with pytest.raises(InvalidInputError, match="недоступно"):
            await container.technical_questions.apply_action(question.id, QuestionActionKind.RETRY)
        ignored = await container.technical_questions.apply_action(
            question.id, QuestionActionKind.CONTINUE_WITHOUT
        )
        assert ignored.status is QuestionStatus.IGNORED
        # Открытие настроек ничего не меняет на сервере.
        waiting = await container.technical_questions.create(
            project_id,
            TechnicalQuestionKind.CREDENTIAL_INVALID,
            "Ключ отклонён провайдером.",
            blocking=False,
        )
        same = await container.technical_questions.apply_action(
            waiting.id, QuestionActionKind.OPEN_SETTINGS
        )
        assert same.status is QuestionStatus.OPEN
        assert same.blocking is False
    finally:
        await container.spawner.shutdown()


# ---------- HTTP ----------


def _wait_http(client: TestClient, run_id: str, status: str) -> dict:
    for _ in range(500):
        run = client.get(f"{API}/runs/{run_id}").json()
        if run["status"] == status:
            return run
        if run["status"] in {"failed", "cancelled", "succeeded"}:
            raise AssertionError(f"Прогон завершился статусом {run['status']}: {run.get('error')}")
        time.sleep(0.01)
    raise AssertionError(f"Прогон не перешёл в {status}")


def test_waiting_run_resume_endpoint_and_technical_question_api(
    client: TestClient, container: Container
) -> None:
    container.runs._resolver.server_pipeline = BudgetThenMock()
    response = client.post(
        f"{API}/projects/{DEMO_PROJECT_ID}/runs",
        json={"mode": "analyze", "profile": {"budget": {"tokens": 10}}},
    )
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    waiting = _wait_http(client, run_id, "waiting")
    assert waiting["stage_label"] == "Ждёт вашего действия"
    assert waiting["cost"] is not None  # неудачная попытка уже записана в журнал вызовов

    technical = client.get(
        f"{API}/projects/{DEMO_PROJECT_ID}/questions", params={"category": "technical"}
    ).json()
    assert len(technical) == 1
    question = technical[0]
    assert question["category"] == "technical"
    assert question["kind"] == "budget_reached"
    assert question["blocking"] is True
    assert [action["kind"] for action in question["actions"]] == [
        "raise_budget",
        "open_settings",
    ]
    business = client.get(
        f"{API}/projects/{DEMO_PROJECT_ID}/questions", params={"category": "business"}
    ).json()
    assert question["id"] not in {item["id"] for item in business}

    # Технический вопрос не отвечается текстом.
    answer = client.post(f"{API}/questions/{question['id']}/answer", json={"text": "Не надо"})
    assert answer.status_code == 422

    # Действие «поднять бюджет» продолжает ожидающий прогон.
    raised = client.post(
        f"{API}/questions/{question['id']}/actions",
        json={"action": "raise_budget", "budget": {"tokens": 500}},
    )
    assert raised.status_code == 200, raised.text
    assert raised.json()["status"] == "resolved"
    finished = _wait_http(client, run_id, "succeeded")
    assert finished["cost"] is not None
    # Первая попытка упала на бюджете и тоже записана в журнал вызовов, вторая — успешная.
    assert finished["cost"]["calls"] == 2
    assert finished["cost"]["cost_usd"] is None  # mock-провайдер не сообщает токены


def test_budget_on_mock_model_is_rejected(client: TestClient) -> None:
    project_id = create_project(client)
    add_text(client, project_id, "Оператор принимает заявку.")
    response = client.post(
        f"{API}/projects/{project_id}/runs",
        json={"mode": "analyze", "profile": {"budget": {"tokens": 100}}},
    )
    assert response.status_code == 422
    assert "демонстрационной модели" in response.json()["detail"]


def test_budget_requires_a_bound(client: TestClient) -> None:
    project_id = create_project(client)
    add_text(client, project_id, "Оператор принимает заявку.")
    response = client.post(
        f"{API}/projects/{project_id}/runs",
        json={"mode": "analyze", "profile": {"budget": {}}},
    )
    assert response.status_code == 422


def test_question_actions_validation(client: TestClient, container: Container) -> None:
    missing = "00000000-0000-0000-0000-000000000000"
    response = client.post(f"{API}/questions/{missing}/actions", json={"action": "open_settings"})
    assert response.status_code == 404

    business = client.get(f"{API}/projects/{DEMO_PROJECT_ID}/questions").json()[0]
    rejected = client.post(
        f"{API}/questions/{business['id']}/actions", json={"action": "open_settings"}
    )
    assert rejected.status_code == 422
    assert "технических" in rejected.json()["detail"]

    unknown = client.post(f"{API}/questions/{business['id']}/actions", json={"action": "dance"})
    assert unknown.status_code == 422
