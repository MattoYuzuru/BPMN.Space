"""Веб-инструменты агентного режима (RFC-0006, шаг 6): поиск, чтение, кеш прогона, отказы.

Сети нет: `httpx.MockTransport` отвечает записанными ответами провайдеров, ключи — настоящие
строки `user_credentials` в in-memory хранилище, маршрутизация — боевой `CapabilityRouter`.
Проверяется, что сервис возвращает датированные ссылки и текст страницы, дедуплицирует и кеширует
результаты, отклоняет закрытые адреса (SSRF) и превращает отказ возможности в технический вопрос.
"""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.container import build_container
from app.domain.capabilities import (
    Capability,
    CapabilityIncident,
    CapabilityIncidentSink,
    CredentialKind,
)
from app.domain.credentials import Credential
from app.domain.models import (
    Project,
    QuestionCategory,
    TechnicalQuestionKind,
)
from app.infra.crypto import CredentialCipher
from app.infra.repositories.base import Repositories
from app.infra.repositories.memory import InMemoryStore
from app.ingest.adapters import build_default_registry
from app.main import create_app
from app.services.auth import optional_user
from app.services.capability_incidents import TechnicalQuestionIncidentSink
from app.services.capability_router import CapabilityRouter, RoutingPolicy
from app.services.common import Runtime
from app.services.errors import InvalidInputError
from app.services.technical_questions import TechnicalQuestionService
from app.services.web_tools import (
    MAX_PAGE_CHARS,
    WebTools,
    canonical_page_url,
    checked_limit,
    checked_page_url,
)

API = "/api/v1"
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
USER_ID = uuid4()
KEY = "test-web-provider-key-0001"
PROJECT_ID = uuid4()
PAGE_URL = "https://example.com/process"


async def _no_sleep(_: float) -> None:
    return None


class FakeSink:
    """Приёмник событий: запоминает отказы возможностей вместо создания вопросов."""

    def __init__(self) -> None:
        self.incidents: list[CapabilityIncident] = []

    async def report(self, incident: CapabilityIncident) -> None:
        self.incidents.append(incident)


class FakeProviders:
    """Ответы провайдеров по хосту; считает запросы для проверки кеша и SSRF."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.search_status = 200
        self.search_body = "Ошибка провайдера"
        self.page_markdown = "# Процесс\n\nЗаявка согласуется за три дня."
        self.firecrawl_canonical = "https://example.com/process-canonical"

    def handler(self, request: httpx.Request) -> httpx.Response:  # noqa: PLR0911
        """Пять провайдеров в одном фейке: один `return` на хост."""
        self.requests.append(request)
        host = request.url.host
        if host == "api.tavily.com":
            if self.search_status != 200:
                return httpx.Response(self.search_status, text=self.search_body)
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "title": "Регламент согласования",
                            "url": "https://example.com/reg?utm_source=mail#top",
                            "content": "Заявка уходит на согласование",
                            "published_date": "2026-10-30",
                        },
                        {
                            "title": "Дубль",
                            "url": "https://example.com/reg",
                            "content": "Копия",
                        },
                        {
                            "title": "Второй результат",
                            "url": "https://example.com/second",
                            "content": "Ещё один документ",
                        },
                    ]
                },
            )
        if host == "api.search.brave.com":
            return httpx.Response(200, json={"web": {"results": []}})
        if host == "api.exa.ai":
            return httpx.Response(200, json={"results": []})
        if host == "r.jina.ai":
            return httpx.Response(
                200,
                text=(
                    "Title: Процесс\n\n"
                    "URL Source: https://example.com/process?utm_campaign=mail\n\n"
                    "Markdown Content:\n# Процесс\n\nЗаявка согласуется за три дня.\n"
                ),
            )
        if host == "api.firecrawl.dev":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "markdown": self.page_markdown,
                        "metadata": {
                            "title": "Процесс согласования",
                            "canonical": self.firecrawl_canonical,
                            "publishedTime": "2026-10-27T08:00:00+03:00",
                        },
                    },
                },
            )
        return httpx.Response(404, text="unknown host")


class Harness:
    """Маршрутизатор на ключах пользователя и сервис веб-инструментов без сети."""

    def __init__(self, *, sink: CapabilityIncidentSink | None = None) -> None:
        self.store = InMemoryStore()
        self.repos: Repositories = self.store.repositories()
        self.cipher = CredentialCipher(
            SecretStr(Fernet.generate_key().decode()), allow_ephemeral=False
        )
        self.providers = FakeProviders()
        self.sink: CapabilityIncidentSink = sink or FakeSink()
        self.registry = build_default_registry()
        self.router = CapabilityRouter(
            self.repos,
            cipher=self.cipher,
            registry=self.registry,
            runtime=Runtime(clock=lambda: NOW),
            policy=RoutingPolicy(
                max_attempts=1,
                retry_base_sec=0,
                retry_max_sec=0,
                breaker_threshold=3,
                breaker_cooldown_sec=60,
                quota_cooldown_sec=3600,
            ),
            transport=httpx.MockTransport(self.providers.handler),
            monotonic=lambda: 1000.0,
            sleep=_no_sleep,
        )
        self.tools = WebTools(
            self.router,
            incident_sink=self.sink,
            runtime=Runtime(clock=lambda: NOW),
        )

    async def add_credential(
        self,
        provider: str,
        kinds: tuple[CredentialKind, ...],
        *,
        priority: int = 100,
        user_id: UUID | None = None,
    ) -> Credential:
        owner = user_id or USER_ID
        credential = Credential(
            id=uuid4(),
            user_id=owner,
            provider=provider,
            label=f"{provider} (тест)",
            encrypted_key=self.cipher.encrypt(owner, KEY),
            key_hint=KEY[-4:],
            kinds=kinds,
            priority=priority,
            enabled=True,
            created_at=NOW,
        )
        await self.repos.credentials.save(credential)  # type: ignore[union-attr]
        return credential


@pytest.fixture
def harness() -> Harness:
    return Harness()


# --- Поиск -----------------------------------------------------------------------------------


async def test_search_returns_dated_results_and_caches(harness: Harness) -> None:
    await harness.add_credential("tavily", (CredentialKind.WEB_SEARCH,))
    session = harness.tools.session(user_id=USER_ID)

    result = await session.search_web("согласование заявки", recency_days=7)

    assert result.ok
    assert result.provider == "tavily"
    assert len(result.results) == 2
    first = result.results[0]
    assert first.url == "https://example.com/reg"
    assert first.published_at == datetime(2026, 10, 30, tzinfo=UTC)
    assert first.source == "tavily"
    assert first.trust.value == "external"
    assert [item.url for item in result.results] == [
        "https://example.com/reg",
        "https://example.com/second",
    ]
    body = result.to_json()
    assert body["status"] == "ok"
    assert body["results"][0]["published_at"].startswith("2026-10-30")

    # Повторный запрос не платит провайдеру дважды: кеш прогона.
    again = await session.search_web("согласование заявки", recency_days=7)
    assert again.cached is True
    assert again.results == result.results
    assert len(harness.providers.requests) == 1


async def test_search_passes_recency_and_clamps_limit(harness: Harness) -> None:
    await harness.add_credential("tavily", (CredentialKind.WEB_SEARCH,))
    session = harness.tools.session(user_id=USER_ID)

    await session.search_web("заявка", recency_days=7, limit=50)

    request = harness.providers.requests[0]
    body = json_body(request)
    assert body["time_range"] == "week"
    assert body["max_results"] == 10


async def test_search_dedupes_links_between_queries(harness: Harness) -> None:
    await harness.add_credential("tavily", (CredentialKind.WEB_SEARCH,))
    session = harness.tools.session(user_id=USER_ID)

    first = await session.search_web("согласование")
    # Второй запрос провайдер отвечает теми же адресами — модели они уже показаны.
    second = await session.search_web("согласование заявки")

    assert len(first.results) == 2
    assert second.results == ()


async def test_search_without_keys_returns_structured_failure(harness: Harness) -> None:
    sink = harness.sink
    assert isinstance(sink, FakeSink)

    result = await harness.tools.search_web(
        user_id=USER_ID, query="согласование", project_id=PROJECT_ID
    )

    assert result.ok is False
    assert result.status == "unavailable"
    assert result.reason == "capability_missing"
    assert result.message is not None
    assert result.to_json()["reason"] == "capability_missing"
    assert len(sink.incidents) == 1
    incident = sink.incidents[0]
    assert incident.capability is Capability.WEB_SEARCH
    assert incident.project_id == PROJECT_ID
    assert incident.reason == "capability_missing"


@pytest.mark.parametrize(
    ("status", "body", "reason"),
    [
        (429, "insufficient_quota", "quota_exhausted"),
        (401, "invalid api key", "auth"),
        (413, "too large", "unsupported"),
    ],
)
async def test_search_failure_class_is_structured(
    harness: Harness, status: int, body: str, reason: str
) -> None:
    await harness.add_credential("tavily", (CredentialKind.WEB_SEARCH,))
    harness.providers.search_status = status
    harness.providers.search_body = body

    result = await harness.tools.search_web(
        user_id=USER_ID, query="согласование", project_id=PROJECT_ID
    )

    assert result.ok is False
    assert result.reason == reason
    assert result.outcome is not None
    assert result.outcome.to_json()["reason"] == reason
    sink = harness.sink
    assert isinstance(sink, FakeSink)
    assert sink.incidents[0].reason == reason


async def test_empty_query_is_rejected(harness: Harness) -> None:
    with pytest.raises(InvalidInputError):
        await harness.tools.search_web(user_id=USER_ID, query="   ")


# --- Чтение страницы -------------------------------------------------------------------------


async def test_read_url_returns_canonical_date_and_fetched_at(harness: Harness) -> None:
    await harness.add_credential("firecrawl", (CredentialKind.WEB_FETCH,))

    result = await harness.tools.read_url(user_id=USER_ID, url=PAGE_URL + "?utm_source=mail")

    assert result.ok
    assert result.provider == "firecrawl"
    assert result.title == "Процесс согласования"
    assert result.canonical_url == "https://example.com/process-canonical"
    assert result.published_at == datetime(2026, 10, 27, 5, 0, tzinfo=UTC)
    assert result.fetched_at == NOW
    assert result.text.startswith("# Процесс")
    assert result.trust.value == "external"
    payload = result.to_json()
    assert payload["canonical_url"] == "https://example.com/process-canonical"
    assert payload["fetched_at"].startswith("2026-11-04T12:00:00")


async def test_read_url_uses_provider_url_source_as_canonical(harness: Harness) -> None:
    await harness.add_credential("jina", (CredentialKind.WEB_FETCH,))

    result = await harness.tools.read_url(user_id=USER_ID, url=PAGE_URL)

    assert result.ok
    assert result.provider == "jina"
    assert result.title == "Процесс"
    assert result.canonical_url == "https://example.com/process"
    assert "Заявка согласуется" in result.text


async def test_read_url_ignores_private_provider_canonical(harness: Harness) -> None:
    """Метаданные провайдера не довереннее страницы: закрытый canonical не попадает в провенанс."""
    await harness.add_credential("firecrawl", (CredentialKind.WEB_FETCH,))
    harness.providers.firecrawl_canonical = "http://127.0.0.1/internal"

    result = await harness.tools.read_url(user_id=USER_ID, url=PAGE_URL)

    assert result.ok
    assert result.canonical_url == "https://example.com/process"


async def test_read_url_caches_page(harness: Harness) -> None:
    await harness.add_credential("firecrawl", (CredentialKind.WEB_FETCH,))
    session = harness.tools.session(user_id=USER_ID)

    first = await session.read_url(PAGE_URL)
    second = await session.read_url(PAGE_URL + "#anchor")

    assert first.ok
    assert second.ok
    assert second.cached is True
    assert second.text == first.text
    assert len(harness.providers.requests) == 1


async def test_read_url_truncates_long_page(harness: Harness) -> None:
    await harness.add_credential("firecrawl", (CredentialKind.WEB_FETCH,))
    harness.providers.page_markdown = "я" * (MAX_PAGE_CHARS + 500)

    result = await harness.tools.read_url(user_id=USER_ID, url=PAGE_URL)

    assert result.ok
    assert result.truncated is True
    assert len(result.text) == MAX_PAGE_CHARS
    assert result.to_json()["truncated"] is True


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/admin",
        "http://localhost.localdomain/",
        "http://127.0.0.1:8000/",
        "http://10.0.0.5/internal",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://[::1]/",
        "http://0.0.0.0/",
        "https://internal.corp/process",
        "file:///etc/passwd",
        "ftp://example.com/process",
        "https://" + "user" + ":" + "password" + "@example.com/",
        "",
    ],
)
async def test_read_url_rejects_unsafe_address_without_request(harness: Harness, url: str) -> None:
    await harness.add_credential("firecrawl", (CredentialKind.WEB_FETCH,))

    with pytest.raises(InvalidInputError):
        await harness.tools.read_url(user_id=USER_ID, url=url)
    assert harness.providers.requests == []


async def test_read_url_without_keys_is_structured_failure(harness: Harness) -> None:
    result = await harness.tools.read_url(user_id=USER_ID, url=PAGE_URL, project_id=PROJECT_ID)

    assert result.ok is False
    assert result.reason == "capability_missing"
    assert result.canonical_url == "https://example.com/process"
    assert result.to_json()["status"] == "unavailable"


# --- Стыковка с техническими вопросами ------------------------------------------------------


async def _repos_with_project() -> tuple[Repositories, Project]:
    store = InMemoryStore()
    repos = store.repositories()
    project = Project(
        id=PROJECT_ID, title="Процесс", description=None, created_at=NOW, updated_at=NOW
    )
    await repos.projects.add(project)
    return repos, project


async def test_incident_sink_creates_technical_question() -> None:
    repos, project = await _repos_with_project()
    questions = TechnicalQuestionService(repos, runtime=Runtime(clock=lambda: NOW))
    sink = TechnicalQuestionIncidentSink(questions, repos)
    harness = Harness(sink=sink)
    harness.repos = repos

    result = await harness.tools.search_web(
        user_id=USER_ID, query="согласование", project_id=project.id
    )

    assert result.ok is False
    created = await repos.questions.list_by_project(project.id)
    assert len(created) == 1
    question = created[0]
    assert question.category is QuestionCategory.TECHNICAL
    assert question.kind is TechnicalQuestionKind.CAPABILITY_MISSING
    assert question.blocking is False


# --- Ограничения и нормализация адресов ------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.com/A?b=1#frag", "https://example.com/A?b=1"),
        ("https://example.com/A?utm_source=x&b=1", "https://example.com/A?b=1"),
        ("https://example.com", "https://example.com/"),
    ],
)
def test_canonical_page_url(url: str, expected: str) -> None:
    assert canonical_page_url(url) == expected


def test_checked_page_url_accepts_public_page() -> None:
    assert checked_page_url("  https://example.com/process  ") == "https://example.com/process"


def test_checked_limit_clamps() -> None:
    assert checked_limit(0) == 1
    assert checked_limit(99) == 10


# --- HTTP: ключ веб-поиска принимается, карточки показывают провайдеров ---------------------


class HttpStack:
    def __init__(self) -> None:
        settings = Settings(
            mock_delay_scale=0,
            auth_enabled=False,
            seed_demo_data=True,
            credentials_encryption_key=SecretStr(Fernet.generate_key().decode()),
            rate_limit_enabled=False,
            capability_retry_base_sec=0,
            capability_retry_max_sec=0,
        )
        self.providers = FakeProviders()
        self.user = SimpleNamespace(id=USER_ID, email="web@example.com")
        self.container = build_container(
            settings, adapter_transport=httpx.MockTransport(self.providers.handler)
        )
        self.app = create_app(settings, container=self.container)
        self.app.dependency_overrides[optional_user] = lambda: self.user


def test_web_search_key_is_accepted_and_capability_cards_show_providers() -> None:
    stack = HttpStack()
    with TestClient(stack.app) as client:
        created = client.post(
            f"{API}/me/credentials",
            json={"kinds": ["web_search"], "provider": "tavily", "api_key": KEY},
        )
        assert created.status_code == 201, created.text
        listing = client.get(f"{API}/me/credentials")
        assert listing.status_code == 200
        cards = {card["capability"]: card for card in listing.json()["capabilities"]}
        search_card = cards["web_search"]
        assert search_card["keys"] == 1
        assert search_card["available"] is True
        assert {item["id"] for item in search_card["providers"]} == {
            "tavily",
            "brave",
            "exa",
        }
        assert cards["web_fetch"]["providers"]


def test_unsupported_provider_for_web_fetch_is_rejected() -> None:
    stack = HttpStack()
    with TestClient(stack.app) as client:
        response = client.post(
            f"{API}/me/credentials",
            json={"kinds": ["web_fetch"], "provider": "tavily", "api_key": KEY},
        )
        assert response.status_code == 422
        assert "не умеет" in response.json()["detail"]


def json_body(request: httpx.Request) -> dict[str, object]:
    return json.loads(request.content)
