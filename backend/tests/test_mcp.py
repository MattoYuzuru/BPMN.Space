"""MCP-сервер (RFC-0007, шаг 2): клиент SDK, права, провенанс, ресурсы и подсказки.

Часть тестов — без PostgreSQL: сборка сервера, закрытая по умолчанию таблица прав,
подписанные допуски оценки и сокрытие внутренних полей. HTTP-сценарии с токенами идут через
настоящий ASGI-стек и PostgreSQL (фикстура `stack` из `test_auth_http`, временная схема);
без TEST_DATABASE_URL они пропускаются (см. `make test-postgres`).
"""

# Фикстура `stack` импортируется из test_auth_http: параметры тестов её «переопределяют».
# ruff: noqa: F811

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import httpx2
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp_types import CallToolResult
from sqlalchemy import update

from app.config import Settings
from app.container import build_container
from app.domain.api_tokens import ApiScope
from app.domain.models import (
    ANSWER_VIA_AGENT,
    Answer,
    Question,
    QuestionKind,
    QuestionStatus,
    Run,
    RunMode,
    RunStatus,
    Severity,
    Source,
    SourceKind,
    SourceOrigin,
    SourceStatus,
    SourceTrust,
)
from app.infra.db_models import ApiTokenRow
from app.llm.estimate import (
    CostRange as DomainCostRange,
)
from app.llm.estimate import (
    IntRange as DomainIntRange,
)
from app.llm.estimate import (
    RunEstimate as DomainRunEstimate,
)
from app.llm.estimate import (
    StageEstimate as DomainStageEstimate,
)
from app.mcp import build_mcp
from app.mcp.auth import (
    PROMPT_POLICIES,
    RESOURCE_POLICIES,
    TOOL_POLICIES,
    TokenRateLimiter,
    tool_policy,
)
from app.mcp.estimate import (
    ESTIMATE_UNAVAILABLE_MESSAGE,
    ServiceEstimator,
    TicketSigner,
    UnavailableEstimator,
    _from_domain,
    build_estimator,
)
from app.mcp.serializers import question_view, run_view, source_view
from app.mcp.tools import MAX_READ_CHARS, _profile_json
from app.services.errors import ForbiddenError, InvalidInputError, UnavailableError
from tests.test_auth_http import (  # noqa: F401 — фикстура `stack` подключается импортом
    API,
    PASSWORD,
    Account,
    Stack,
    _finished_project,
    stack,
)

MCP_URL = "http://t/mcp"
INITIALIZE = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
Connect = Callable[[str | None], Awaitable[ClientSession]]


# ---------- вспомогательные -----------------


def _offline_container(*, auth_enabled: bool = False) -> Any:
    settings = Settings(
        database_url=None,
        auth_enabled=auth_enabled,
        app_env="test",
        mock_delay_scale=0,
        seed_demo_data=False,
        rate_limit_enabled=False,
        llm_provider="mock",
        stt_provider="mock",
    )
    return build_container(settings)


@asynccontextmanager
async def _mcp_server(stack: Stack) -> AsyncIterator[Connect]:
    """Запустить менеджер сессий MCP (FastAPI его не запускает) и раздать клиентов по токенам."""
    async with stack.app.state.mcp.lifespan(), AsyncExitStack() as exit_stack:

        async def connect(secret: str | None) -> ClientSession:
            headers = {"authorization": f"Bearer {secret}"} if secret else {}
            http = httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=stack.app),
                base_url="http://t",
                headers=headers,
            )
            await exit_stack.enter_async_context(http)
            streams = await exit_stack.enter_async_context(
                streamable_http_client(MCP_URL, http_client=http)
            )
            session = await exit_stack.enter_async_context(ClientSession(*streams))
            await session.initialize()
            return session

        yield connect


async def _issue_token(owner: Account, **body: Any) -> tuple[str, str]:
    """Создать токен владельца (cookie-сессия + CSRF) и вернуть секрет и название."""
    created = await owner.post("/me/api-tokens", json={"name": "Claude Code", **body})
    assert created.status_code == 201, created.text
    data = created.json()
    return data["secret"], data["name"]


async def _call(
    session: ClientSession, name: str, arguments: dict[str, Any] | None = None
) -> CallToolResult:
    return await session.call_tool(name, arguments or {})


def _text_of(item: Any) -> str:
    """Текстовый блок контента MCP; у картинок, аудио и ссылок текста нет."""
    text = getattr(item, "text", "")
    return text if isinstance(text, str) else ""


def _payload(result: CallToolResult) -> dict[str, Any]:
    """Тело успешного инструмента: structured content или JSON в текстовом блоке."""
    assert not result.is_error, _error(result)
    if result.structured_content is not None:
        return result.structured_content
    text = "".join(_text_of(item) for item in result.content)
    return json.loads(text)


def _error(result: CallToolResult) -> str:
    assert result.is_error, result
    return " ".join(_text_of(item) for item in result.content)


# ---------- без PostgreSQL: устройство сервера и допусков ----------


async def test_every_surface_declares_policy_and_unknown_is_closed() -> None:
    """Таблица прав — источник истины: необъявленный инструмент/ресурс/подсказка закрыты."""
    runtime = build_mcp(_offline_container())
    tools = {tool.name for tool in await runtime.server.list_tools()}
    resources = {tpl.name for tpl in await runtime.server.list_resource_templates()}
    prompts = {prompt.name for prompt in await runtime.server.list_prompts()}

    assert tools == set(TOOL_POLICIES)
    assert resources == set(RESOURCE_POLICIES)
    assert prompts == set(PROMPT_POLICIES)
    with pytest.raises(ForbiddenError):
        tool_policy("drop_database")


async def test_tool_annotations_show_destructive_and_read_only() -> None:
    runtime = build_mcp(_offline_container())
    tools = {tool.name: tool for tool in await runtime.server.list_tools()}
    assert tools["delete_source"].annotations is not None
    assert tools["delete_source"].annotations.destructive_hint is True
    assert tools["list_projects"].annotations is not None
    assert tools["list_projects"].annotations.read_only_hint is True
    assert tools["start_run"].annotations is not None
    assert tools["start_run"].annotations.read_only_hint is False


def test_estimate_ticket_binds_user_project_mode_profile() -> None:
    signer = TicketSigner(b"secret", ttl_sec=900)
    project, user = uuid4(), uuid4()
    ticket, issued = signer.issue(
        project_id=project, user_id=user, mode=RunMode.BUILD, profile={"effort": "high"}
    )
    parsed = signer.verify(
        ticket,
        project_id=project,
        user_id=user,
        mode=RunMode.BUILD,
        profile={"effort": "high"},
    )
    assert parsed.estimate_id == issued.estimate_id
    assert parsed.profile == {"effort": "high"}

    for mismatched in (
        {
            "project_id": uuid4(),
            "user_id": user,
            "mode": RunMode.BUILD,
            "profile": {"effort": "high"},
        },
        {
            "project_id": project,
            "user_id": uuid4(),
            "mode": RunMode.BUILD,
            "profile": {"effort": "high"},
        },
        {
            "project_id": project,
            "user_id": user,
            "mode": RunMode.ANALYZE,
            "profile": {"effort": "high"},
        },
        {
            "project_id": project,
            "user_id": user,
            "mode": RunMode.BUILD,
            "profile": {"effort": "low"},
        },
    ):
        with pytest.raises(InvalidInputError):
            signer.verify(ticket, **mismatched)

    tampered = ticket[:-2] + ("aa" if not ticket.endswith("aa") else "bb")
    with pytest.raises(InvalidInputError):
        signer.decode(tampered)


def test_estimate_ticket_expires() -> None:
    signer = TicketSigner(b"secret", ttl_sec=-1)
    ticket, _ = signer.issue(
        project_id=uuid4(), user_id=uuid4(), mode=RunMode.ANALYZE, profile=None
    )
    with pytest.raises(InvalidInputError):
        signer.decode(ticket)


async def test_estimator_absent_is_explicit() -> None:
    with pytest.raises(UnavailableError) as caught:
        await UnavailableEstimator().estimate(
            project_id=uuid4(), mode=RunMode.ANALYZE, profile=None, user_id=uuid4()
        )
    assert caught.value.message == ESTIMATE_UNAVAILABLE_MESSAGE


def _domain_estimate(*, cost: DomainCostRange | None) -> DomainRunEstimate:
    """Ответ сервиса оценки 2A для проверки адаптера (RFC-0005)."""
    return DomainRunEstimate(
        tokens=DomainIntRange(min=1000, max=4000),
        calls=DomainIntRange(min=2, max=6),
        cost=cost,
        duration_sec=DomainIntRange(min=30, max=120),
        breakdown=[
            DomainStageEstimate(
                stage="analyze",
                label="Сверка вопросов",
                calls=DomainIntRange(min=1, max=3),
                tokens_in=DomainIntRange(min=500, max=2000),
                tokens_out=DomainIntRange(min=100, max=400),
                cost=cost,
            )
        ],
        complete=cost is not None,
        priced_on=None,
        notes=["Запросы к модели не входят в обработку медиа"],
        model="claude-opus-5",
        provider="anthropic",
    )


async def test_service_estimator_maps_real_estimate() -> None:
    seen: dict[str, Any] = {}

    class FakeService:
        async def estimate(self, project_id: Any, **kwargs: Any) -> DomainRunEstimate:
            seen.update({"project_id": project_id, **kwargs})
            return _domain_estimate(cost=DomainCostRange(min_usd=0.5, max_usd=2.5, currency="USD"))

    project, user = uuid4(), uuid4()
    mapped = await ServiceEstimator(FakeService()).estimate(
        project_id=project,
        mode=RunMode.BUILD,
        profile={"effort": "high", "semantic_review": False},
        user_id=user,
    )
    assert seen["project_id"] == project
    assert seen["mode"] is RunMode.BUILD
    assert seen["created_by"] == user
    assert seen["profile"] is not None
    assert seen["profile"].effort == "high"
    assert seen["profile"].semantic_review is False

    body = mapped.to_json()
    assert body["tokens"] == {"min": 1000, "max": 4000}
    assert body["calls"] == {"min": 2, "max": 6}
    assert body["duration_sec"] == {"min": 30, "max": 120}
    assert body["cost"] == {"min": 0.5, "max": 2.5, "currency": "USD"}
    assert body["complete"] is True
    assert body["model"] == "claude-opus-5"
    assert body["provider"] == "anthropic"
    assert body["breakdown"][0]["stage"] == "analyze"
    assert body["notes"]


async def test_service_estimator_is_honest_when_prices_unknown() -> None:
    class FakeService:
        async def estimate(self, project_id: Any, **kwargs: Any) -> DomainRunEstimate:
            return _domain_estimate(cost=None)

    mapped = await ServiceEstimator(FakeService()).estimate(
        project_id=uuid4(), mode=RunMode.ANALYZE, profile=None, user_id=uuid4()
    )
    body = mapped.to_json()
    assert body["cost"] is None
    assert body["complete"] is False
    assert body["tokens"]["max"] >= body["tokens"]["min"]


def test_from_domain_drops_partial_cost_and_marks_incomplete() -> None:
    estimate = _domain_estimate(cost=DomainCostRange(min_usd=None, max_usd=2.0))
    mapped = _from_domain(estimate)
    assert mapped.cost is None
    assert mapped.complete is False
    assert mapped.to_json()["cost"] is None


def test_build_estimator_uses_container_service() -> None:
    marker = object()
    assert isinstance(build_estimator(cast(Any, _FakeContainer(marker))), ServiceEstimator)
    assert isinstance(build_estimator(cast(Any, _FakeContainer(None))), UnavailableEstimator)


class _FakeContainer:
    def __init__(self, estimate: Any) -> None:
        self.estimate = estimate


def test_agent_cannot_raise_budget_or_smuggle_profile_fields() -> None:
    for budget in (
        {"budget": {"cost_usd": 10}},
        {"budget_cost_usd": 10},
        {"max_cost_usd": 10},
    ):
        with pytest.raises(InvalidInputError):
            _profile_json(budget)
    assert _profile_json({"effort": "high", "semantic_review": True}) == {
        "effort": "high",
        "semantic_review": True,
    }
    assert _profile_json({"effort": None}) is None
    with pytest.raises(InvalidInputError):
        _profile_json({"effort": "turbo"})


def test_token_rate_limiter_counts_per_token() -> None:
    now = [100.0]
    limiter = TokenRateLimiter(limit=2, window=60.0, clock=lambda: now[0])
    assert limiter.check("a") is None
    assert limiter.check("a") is None
    assert limiter.check("a") is not None
    assert limiter.check("b") is None  # другой токен не страдает
    now[0] += 61
    assert limiter.check("a") is None


def test_serializers_hide_internal_fields_and_provider_errors() -> None:
    source = Source(
        id=uuid4(),
        project_id=uuid4(),
        kind=SourceKind.TEXT,
        title="Материал",
        content="Текст",
        status=SourceStatus.READY,
        active=True,
        created_at=datetime(2026, 11, 4, tzinfo=UTC),
        origin=SourceOrigin.AGENT,
        trust=SourceTrust.AGENT,
        file_key="uploads/secret",
        digest="digest",
    )
    data = source_view(source)
    assert "file_key" not in data
    assert "digest" not in data
    assert "content" not in data
    assert data["origin"] == "agent"

    question = Question(
        id=uuid4(),
        project_id=uuid4(),
        code="Q-1",
        kind=QuestionKind.MISSING_ACTOR,
        severity=Severity.MAJOR,
        status=QuestionStatus.ANSWERED,
        text="Кто согласует?",
        assumption="Допущение",
        created_at=datetime(2026, 11, 4, tzinfo=UTC),
        updated_at=datetime(2026, 11, 4, tzinfo=UTC),
        answer=Answer(source_id=uuid4(), text="Начальник", via=ANSWER_VIA_AGENT, via_name="Claude"),
    )
    view = question_view(question)
    assert view["answer"]["via"] == "agent"
    assert view["answer"]["via_name"] == "Claude"

    run = Run(
        id=uuid4(),
        project_id=uuid4(),
        mode=RunMode.ANALYZE,
        status=RunStatus.FAILED,
        started_at=datetime(2026, 11, 4, tzinfo=UTC),
        error="provider said key sk-secret at 10.0.0.1",
    )
    run_data = run_view(run)
    assert "error" not in run_data
    assert "sk-secret" not in json.dumps(run_data)
    assert run_data["failed"] is True


# ---------- PostgreSQL: HTTP-сценарии через MCP-клиент SDK ----------


async def test_mcp_rejects_missing_unknown_and_broken_tokens(stack: Stack) -> None:
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=stack.app), base_url="http://t"
    ) as http:
        missing = await http.post("/mcp", json=INITIALIZE)
        assert missing.status_code == 401
        assert missing.headers["www-authenticate"].startswith("Bearer")
        unknown = await http.post(
            "/mcp", json=INITIALIZE, headers={"authorization": "Bearer bps_" + "x" * 43}
        )
        assert unknown.status_code == 401
        # Неизвестный и отсутствующий токен неразличимы по телу ответа.
        assert unknown.json() == missing.json()


async def test_mcp_lists_tools_resources_prompts_and_prompt_text(stack: Stack) -> None:
    owner = await stack.user("mcp-tools@example.com")
    secret, _ = await _issue_token(owner)
    async with _mcp_server(stack) as connect:
        session = await connect(secret)
        tools = await session.list_tools()
        assert {tool.name for tool in tools.tools} == set(TOOL_POLICIES)
        templates = await session.list_resource_templates()
        assert {tpl.name for tpl in templates.resource_templates} == set(RESOURCE_POLICIES)
        prompts = await session.list_prompts()
        assert {prompt.name for prompt in prompts.prompts} == set(PROMPT_POLICIES)
        prompt = await session.get_prompt(
            "collect_process_materials",
            {"project": "Договоры", "sources": "Confluence, пространство «Продажи»"},
        )
        text = "".join(_text_of(message.content) for message in prompt.messages)
        assert "add_source" in text
        assert "origin=agent" in text


async def test_mcp_reads_project_sources_in_portions(stack: Stack) -> None:
    owner = await stack.user("mcp-read@example.com")
    finished = await _finished_project(owner)
    secret, _ = await _issue_token(owner)  # по умолчанию projects:read + questions:answer
    async with _mcp_server(stack) as connect:
        session = await connect(secret)
        projects = _payload(await _call(session, "list_projects"))
        card = next(item for item in projects["items"] if item["id"] == finished["project"])
        assert card["access"] == "owner"
        assert projects["total"] >= 1

        detail = _payload(await _call(session, "get_project", {"project_id": finished["project"]}))
        assert detail["latest_version"]["id"] == finished["version"]
        assert detail["questions"]
        assert detail["sources"]
        assert "file_key" not in json.dumps(detail)

        listed = _payload(await _call(session, "list_sources", {"project_id": finished["project"]}))
        assert listed["total"] == len(listed["items"]) >= 1
        source_id = listed["items"][0]["id"]
        first = _payload(await _call(session, "read_source", {"source_id": source_id, "to": 50}))
        assert first["from"] == 0
        assert first["to"] == min(50, first["total_chars"])
        assert len(first["content"]) == first["to"]
        if first["next_from"] is not None:
            second = _payload(
                await _call(
                    session,
                    "read_source",
                    {"source_id": source_id, "from_": first["next_from"]},
                )
            )
            assert second["from"] == first["next_from"]
            assert len(second["content"]) <= MAX_READ_CHARS
        bad = await _call(session, "read_source", {"source_id": "not-a-uuid"})
        assert bad.is_error
        assert "идентификатор" in _error(bad)


async def test_mcp_agent_sources_are_marked_and_deletable_with_confirm(stack: Stack) -> None:
    owner = await stack.user("mcp-write@example.com")
    scopes = ["projects:read", "projects:write", "sources:write", "sources:delete"]
    secret, token_name = await _issue_token(owner, scopes=scopes)
    async with _mcp_server(stack) as connect:
        session = await connect(secret)
        created = _payload(
            await _call(session, "create_project", {"title": "Договоры", "description": "Агент"})
        )
        assert created["access"] == "owner"
        project_id = created["id"]

        added = _payload(
            await _call(
                session,
                "add_source",
                {
                    "project_id": project_id,
                    "text": "Согласование договора: юрист → директор.",
                    "title": "Регламент из Confluence",
                    "url": "https://confluence.example.org/pages/42",
                },
            )
        )
        source = added["source"]
        assert added["origin"] == "agent"
        assert source["origin"] == "agent"
        assert source["trust"] == "agent"
        assert source["derivation"]["params"]["token_name"] == token_name
        assert source["derivation"]["params"]["url"].startswith("https://confluence")

        updated = _payload(
            await _call(
                session,
                "update_source",
                {"source_id": source["id"], "title": "Регламент (проверено агентом)"},
            )
        )
        assert updated["source"]["title"] == "Регламент (проверено агентом)"

        denied = await _call(session, "delete_source", {"source_id": source["id"]})
        assert denied.is_error
        assert "confirm=true" in _error(denied)

        deleted = _payload(
            await _call(session, "delete_source", {"source_id": source["id"], "confirm": True})
        )
        assert deleted["deleted"] is True
        assert (
            _payload(await _call(session, "list_sources", {"project_id": project_id}))["total"] == 0
        )

    # Пометка «через агента» видна и в REST-модели проекта владельца.
    assert (await owner.get(f"/projects/{UUID(project_id)}")).status_code == 200


async def test_mcp_permission_matrix_and_project_scope(stack: Stack) -> None:
    owner = await stack.user("mcp-perm-owner@example.com")
    finished = await _finished_project(owner)
    project_id = finished["project"]
    read_only, _ = await _issue_token(owner, scopes=["projects:read"])
    async with _mcp_server(stack) as connect:
        session = await connect(read_only)
        checks = {
            "add_source": {"project_id": project_id, "text": "текст"},
            "update_source": {"source_id": finished["source"], "title": "x"},
            "delete_source": {"source_id": finished["source"], "confirm": True},
            "save_diagram": {"project_id": project_id, "xml": finished["xml"]},
            "estimate_run": {"project_id": project_id},
            "start_run": {"estimate_token": "garbage"},
        }
        denied_by_scope = {
            "add_source": "sources:write",
            "update_source": "sources:write",
            "delete_source": "sources:delete",
            "save_diagram": "projects:write",
            "estimate_run": "runs:start",
            "start_run": "runs:start",
        }
        for tool, arguments in checks.items():
            result = await _call(session, tool, arguments)
            assert result.is_error, tool
            assert denied_by_scope[tool] in _error(result), tool

        # Чтение и проверка схемы доступны с projects:read.
        diagram = _payload(await _call(session, "get_diagram", {"project_id": project_id}))
        assert diagram["xml"]
        checked = _payload(await _call(session, "check_diagram", {"xml": diagram["xml"]}))
        assert checked["xsd_valid"] is True

    # create_project требует токен без ограничения проектами (all_projects).
    restricted, _ = await _issue_token(
        owner,
        scopes=["projects:read", "projects:write", "sources:write"],
        project_ids=[project_id],
    )
    async with _mcp_server(stack) as connect:
        session = await connect(restricted)
        create = await _call(session, "create_project", {"title": "Новый проект"})
        assert create.is_error
        assert "ограничен" in _error(create)
        listed = _payload(await _call(session, "list_projects"))
        assert [item["id"] for item in listed["items"]] == [project_id]

        # Проект вне токена неотличим от чужого: 404-подобная ошибка, без квитанции.
        other_owner = await stack.user("mcp-perm-other@example.com")
        other = await other_owner.post("/projects", json={"title": "Чужой"})
        other_id = other.json()["id"]
        hidden = await _call(session, "get_project", {"project_id": other_id})
        assert hidden.is_error
        assert "не найден" in _error(hidden).lower()

    # Наблюдатель (viewer) читает, но не меняет.
    stranger = await stack.user("mcp-viewer@example.com")
    viewer_secret, _ = await _issue_token(
        stranger, scopes=["projects:read", "projects:write", "sources:write"]
    )
    link = await owner.post(
        f"/projects/{project_id}/share-links", json={"role": "viewer", "expires_in_days": 7}
    )
    assert link.status_code == 201, link.text
    share_token = link.json()["url_path"].rsplit("/", 1)[-1]
    accepted = await stranger.post(f"/shares/{share_token}/accept")
    assert accepted.status_code in {200, 204}, accepted.text
    async with _mcp_server(stack) as connect:
        viewer = await connect(viewer_secret)
        detail = _payload(await _call(viewer, "get_project", {"project_id": project_id}))
        assert detail["access"] == "viewer"
        denied = await _call(viewer, "add_source", {"project_id": project_id, "text": "нельзя"})
        assert denied.is_error
        assert "редактора" in _error(denied)


async def test_mcp_answers_question_with_agent_provenance(stack: Stack) -> None:
    owner = await stack.user("mcp-answer@example.com")
    finished = await _finished_project(owner)
    project_id = finished["project"]
    question_id = finished["question"]
    listed = (await owner.get(f"/projects/{project_id}/questions")).json()
    target = next((item for item in listed if item["status"] == "open"), None)
    if target is None:
        reopened = await owner.post(f"/questions/{question_id}/reopen")
        assert reopened.status_code == 200, reopened.text
        question_id = reopened.json()["id"]
    else:
        question_id = target["id"]

    secret, token_name = await _issue_token(owner, scopes=["projects:read", "questions:answer"])
    async with _mcp_server(stack) as connect:
        session = await connect(secret)
        answered = _payload(
            await _call(
                session,
                "answer_question",
                {"question_id": question_id, "text": "Согласует начальник отдела"},
            )
        )
        assert answered["answer"]["via"] == ANSWER_VIA_AGENT
        assert answered["answer"]["via_name"] == token_name
        assert answered["status"] == "answered"

    after = (await owner.get(f"/projects/{project_id}/questions")).json()
    stored = next(item for item in after if item["id"] == question_id)
    assert stored["answer"]["via"] == "agent"
    assert stored["answer"]["via_name"] == token_name
    assert stored["answer"]["text"] == "Согласует начальник отдела"


async def test_mcp_diagram_read_save_and_conflict(stack: Stack) -> None:
    owner = await stack.user("mcp-diagram@example.com")
    finished = await _finished_project(owner)
    project_id = finished["project"]
    secret, _ = await _issue_token(owner, scopes=["projects:read", "projects:write"])
    async with _mcp_server(stack) as connect:
        session = await connect(secret)
        diagram = _payload(await _call(session, "get_diagram", {"project_id": project_id}))
        assert diagram["xml"]
        assert diagram["ir"]["nodes"] > 0
        assert diagram["version"]["id"] == finished["version"]
        assert diagram["lanes"]
        lane = diagram["lanes"][0]
        lane_view = _payload(
            await _call(session, "get_diagram", {"project_id": project_id, "lane": lane})
        )
        assert lane_view["lane"]["name"] == lane
        assert lane_view["lane"]["element_ids"]
        assert lane_view["lane"]["elements_count"] >= 1

        checked = _payload(await _call(session, "check_diagram", {"xml": diagram["xml"]}))
        assert checked["xsd_valid"] is True
        assert checked["nodes"] == diagram["ir"]["nodes"]

        updated_xml = diagram["xml"].replace('name="', 'name="Агент ', 1)
        saved = _payload(
            await _call(
                session,
                "save_diagram",
                {
                    "project_id": project_id,
                    "xml": updated_xml,
                    "base_version_id": finished["version"],
                },
            )
        )
        assert saved["version"]["origin"] == "manual"
        assert saved["version"]["number"] > diagram["version"]["number"]

        stale = await _call(
            session,
            "save_diagram",
            {
                "project_id": project_id,
                "xml": updated_xml.replace('name="Агент ', 'name="Агент 2 '),
                "base_version_id": finished["version"],
            },
        )
        assert stale.is_error
        assert "изменена" in _error(stale).lower()


async def test_mcp_estimate_returns_real_estimate_and_starts_run(stack: Stack) -> None:
    owner = await stack.user("mcp-runs@example.com")
    finished = await _finished_project(owner)
    project_id = finished["project"]
    secret, _ = await _issue_token(owner, scopes=["projects:read", "runs:start"])
    async with _mcp_server(stack) as connect:
        session = await connect(secret)
        estimated = _payload(
            await _call(
                session,
                "estimate_run",
                {
                    "project_id": project_id,
                    "kind": "build",
                    "profile": {"effort": "high", "semantic_review": True},
                },
            )
        )
        estimate = estimated["estimate"]
        assert estimate["tokens"]["min"] <= estimate["tokens"]["max"]
        assert estimate["calls"]["max"] >= estimate["calls"]["min"] >= 1
        assert 0 < estimate["duration_sec"]["min"] <= estimate["duration_sec"]["max"]
        assert estimate["breakdown"]
        assert estimate["model"]
        # Mock-провайдер без цен: оценка честно неполная, деньги не выдумываются.
        assert estimated["complete"] is False
        assert estimated["cost_known"] is False
        assert estimate["cost"] is None
        assert estimated["estimate_token"]

        # Профиль сверяется с возможностями: неизвестный effort — понятная ошибка.
        bad_profile = await _call(
            session, "estimate_run", {"project_id": project_id, "profile": {"effort": "turbo"}}
        )
        assert bad_profile.is_error
        assert "effort" in _error(bad_profile)

        # Без свежей оценки запуск отклоняется: тикет не подделать.
        forged = await _call(
            session, "start_run", {"project_id": project_id, "estimate_token": "bps_fake"}
        )
        assert forged.is_error
        assert "устарела" in _error(forged).lower()

        # Свежий тикет запускает прогон; оценка была неполной, но запуск легален.
        started = _payload(
            await _call(
                session,
                "start_run",
                {"project_id": project_id, "estimate_token": estimated["estimate_token"]},
            )
        )
        run_id = started["run"]["id"]
        assert started["run"]["mode"] == "build"
        assert started["run"]["project_id"] == project_id
        run: dict[str, Any] = started["run"]
        for _ in range(100):
            if run["status"] not in {"queued", "running"}:
                break
            await asyncio.sleep(0.05)
            run = _payload(await _call(session, "get_run", {"run_id": run_id}))["run"]
        assert run["status"] == "succeeded", run
        assert run["version_id"]
        # Потрачено: mock без цен даёт complete=false и cost_usd=null, но журнал вызовов есть.
        spent = _payload(await _call(session, "get_run", {"run_id": run_id}))["cost"]
        assert spent is not None
        assert spent["calls"] >= 1
        assert spent["by_stage"]
        assert spent["complete"] is False
        assert spent["cost_usd"] is None

        # Один тикет — только для своего проекта.
        other = await owner.post("/projects", json={"title": "Другой проект"})
        assert other.status_code == 201, other.text
        mismatch = await _call(
            session,
            "start_run",
            {"project_id": other.json()["id"], "estimate_token": estimated["estimate_token"]},
        )
        assert mismatch.is_error
        assert "не совпадает" in _error(mismatch)


async def test_mcp_estimate_rejects_empty_project_and_budget(stack: Stack) -> None:
    owner = await stack.user("mcp-estimate-guard@example.com")
    finished = await _finished_project(owner)
    project_id = finished["project"]
    secret, _ = await _issue_token(owner, scopes=["projects:read", "runs:start"])
    async with _mcp_server(stack) as connect:
        session = await connect(secret)
        # Пустой проект оценить нельзя: сервис отвечает понятной причиной, не выдумкой.
        empty = await owner.post("/projects", json={"title": "Пустой"})
        assert empty.status_code == 201, empty.text
        no_sources = await _call(session, "estimate_run", {"project_id": empty.json()["id"]})
        assert no_sources.is_error
        assert "источник" in _error(no_sources).lower()

        # Бюджет агент задать не может (настройку бюджета добавит волна 2B).
        budget = await _call(
            session,
            "estimate_run",
            {"project_id": project_id, "profile": {"budget_cost_usd": 100}},
        )
        assert budget.is_error
        assert "Бюджет" in _error(budget)


async def test_mcp_viewer_can_estimate_but_not_start(stack: Stack) -> None:
    owner = await stack.user("mcp-viewer-est-owner@example.com")
    finished = await _finished_project(owner)
    project_id = finished["project"]
    stranger = await stack.user("mcp-viewer-est@example.com")
    viewer_secret, _ = await _issue_token(stranger, scopes=["projects:read", "runs:start"])
    link = await owner.post(
        f"/projects/{project_id}/share-links", json={"role": "viewer", "expires_in_days": 7}
    )
    assert link.status_code == 201, link.text
    share_token = link.json()["url_path"].rsplit("/", 1)[-1]
    assert (await stranger.post(f"/shares/{share_token}/accept")).status_code in {200, 204}
    async with _mcp_server(stack) as connect:
        viewer = await connect(viewer_secret)
        viewer_estimate = await _call(
            viewer, "estimate_run", {"project_id": project_id, "kind": "analyze"}
        )
        assert not viewer_estimate.is_error, _error(viewer_estimate)
        viewer_start = await _call(
            viewer,
            "start_run",
            {
                "project_id": project_id,
                "estimate_token": _payload(viewer_estimate)["estimate_token"],
            },
        )
        assert viewer_start.is_error
        assert "редактора" in _error(viewer_start)


async def test_mcp_resources_return_xml_and_questions(stack: Stack) -> None:
    owner = await stack.user("mcp-resources@example.com")
    finished = await _finished_project(owner)
    secret, _ = await _issue_token(owner)
    async with _mcp_server(stack) as connect:
        session = await connect(secret)
        diagram = await session.read_resource(f"project://{finished['project']}/diagram.bpmn")
        xml = _text_of(diagram.contents[0])
        assert xml.startswith("<?xml") or "<bpmn:definitions" in xml
        questions = await session.read_resource(f"project://{finished['project']}/questions")
        payload = json.loads(_text_of(questions.contents[0]))
        assert isinstance(payload, list)
        assert payload
        first_answer = payload[0]["answer"]
        assert first_answer is None or "via" in first_answer


async def test_mcp_revoked_and_expired_token_are_401(stack: Stack) -> None:
    owner = await stack.user("mcp-revoke@example.com")
    revoked_secret, revoked_name = await _issue_token(owner)
    expired_secret, _ = await _issue_token(owner, name="Истёкший")
    tokens = (await owner.get("/me/api-tokens")).json()["items"]
    revoked_id = next(item["id"] for item in tokens if item["name"] == revoked_name)
    expired_id = next(item["id"] for item in tokens if item["name"] == "Истёкший")
    revoked = await owner.delete(f"/me/api-tokens/{revoked_id}")
    assert revoked.status_code == 204
    async with stack.database.sessions.begin() as session:
        now = datetime.now(UTC)
        # CHECK `expires_at > created_at`: сдвигаем окно жизни в прошлое, а не только срок.
        await session.execute(
            update(ApiTokenRow)
            .where(ApiTokenRow.id == UUID(expired_id))
            .values(created_at=now - timedelta(days=2), expires_at=now - timedelta(days=1))
        )

    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=stack.app), base_url="http://t"
    ) as http:
        for secret in (revoked_secret, expired_secret):
            response = await http.post(
                "/mcp", json=INITIALIZE, headers={"authorization": f"Bearer {secret}"}
            )
            assert response.status_code == 401
            assert "недействителен" in response.json()["detail"]


async def test_mcp_responses_do_not_leak_secrets(stack: Stack) -> None:
    owner = await stack.user("mcp-leak@example.com")
    finished = await _finished_project(owner)
    secret, _ = await _issue_token(owner, scopes=list(ApiScope))
    async with _mcp_server(stack) as connect:
        session = await connect(secret)
        outputs: list[str] = []
        for tool, arguments in (
            ("list_projects", {}),
            ("get_project", {"project_id": finished["project"]}),
            ("list_sources", {"project_id": finished["project"]}),
            ("list_questions", {"project_id": finished["project"]}),
            ("get_run", {"run_id": finished["run"]}),
            ("estimate_run", {"project_id": finished["project"]}),
            ("get_diagram", {"project_id": finished["project"]}),
        ):
            result = await _call(session, tool, arguments)
            outputs.append(json.dumps(_payload(result), ensure_ascii=False))
        text = "\n".join(outputs)
        for banned in (secret, "postgresql", "sqlalchemy", "file_key", "digest", "Traceback"):
            assert banned not in text
        runs = _payload(await _call(session, "get_run", {"run_id": finished["run"]}))
        assert "error" not in runs["run"]
        assert runs["run"]["status"] == "succeeded"
