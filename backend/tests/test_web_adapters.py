"""Адаптеры веб-поиска и чтения страниц (RFC-0006, шаг 6): разбор ответов и классы ошибок.

Сети нет: `httpx.MockTransport` отвечает записанными ответами провайдеров. Проверяется, что
Tavily, Brave, Exa, Jina Reader и Firecrawl разбирают выдачу в структурные ссылки с датами,
классифицируют отказы (429/401/403/413/5xx/таймаут) и не отдают наружу текст провайдера.
"""

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from app.domain.capabilities import Capability, CapabilityError, ErrorClass
from app.ingest.adapters.web import (
    WEB_REQUEST_TIMEOUT_SEC,
    WebSearchHit,
    WebSearchRequest,
    clamp_limit,
    clean_snippet,
    dedupe_hits,
    normalize_url,
    parse_published,
    read_limited,
)
from app.ingest.adapters.web_brave import BraveSearchAdapter
from app.ingest.adapters.web_exa import ExaSearchAdapter
from app.ingest.adapters.web_firecrawl import (
    FIRECRAWL_PROVIDER_TIMEOUT_MS,
    FirecrawlFetchAdapter,
)
from app.ingest.adapters.web_jina import JinaReaderAdapter
from app.ingest.adapters.web_tavily import TavilySearchAdapter

KEY = "test-provider-key-0123456789"
SEARCH_REQUEST = WebSearchRequest(query="согласование заявки", limit=3)
PAGE_URL = "https://example.com/process"


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _build(name: str, handler) -> Any:
    transport = _transport(handler)
    match name:
        case "tavily":
            return TavilySearchAdapter(KEY, transport=transport)
        case "brave":
            return BraveSearchAdapter(KEY, transport=transport)
        case "exa":
            return ExaSearchAdapter(KEY, transport=transport)
        case "jina":
            return JinaReaderAdapter(KEY, transport=transport)
        case "firecrawl":
            return FirecrawlFetchAdapter(KEY, transport=transport)
    raise AssertionError(name)


SEARCH_PROVIDERS = ("tavily", "brave", "exa")
FETCH_PROVIDERS = ("jina", "firecrawl")
ALL_PROVIDERS = [*SEARCH_PROVIDERS, *FETCH_PROVIDERS]


async def _invoke(adapter: Any, name: str) -> Any:
    if name in SEARCH_PROVIDERS:
        return await adapter.search(SEARCH_REQUEST)
    return await adapter.fetch(PAGE_URL)


# --- Успешные ответы и разбор выдачи -------------------------------------------------------


async def test_tavily_search_parses_dates_and_dedupes_links() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/search"
        assert request.headers["Authorization"] == f"Bearer {KEY}"
        body = json_body(request)
        assert body["query"] == "согласование заявки"
        assert body["max_results"] == 3
        assert body["time_range"] == "week"
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
                        "url": "https://example.com/reg?utm_source=mail#top",
                        "content": "Тот же адрес",
                    },
                    {
                        "title": "Без ссылки",
                        "url": "",
                        "content": "Мусор",
                    },
                ]
            },
        )

    adapter = TavilySearchAdapter(KEY, transport=_transport(handler), credential_id=None)
    request = WebSearchRequest(query="согласование заявки", recency_days=7, limit=3)
    hits = await adapter.search(request)
    await adapter.aclose()

    assert len(hits) == 1
    hit = hits[0]
    # Нормализованный адрес — только ключ дедупликации; в выдаче остаётся исходный.
    assert hit.url == "https://example.com/reg?utm_source=mail#top"
    assert hit.title == "Регламент согласования"
    assert hit.snippet == "Заявка уходит на согласование"
    assert hit.published_at == datetime(2026, 10, 30, tzinfo=UTC)
    assert hit.source == "tavily"


async def test_brave_search_uses_freshness_word_and_page_age() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/res/v1/web/search"
        assert request.headers["X-Subscription-Token"] == KEY
        seen.update(dict(request.url.params))
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "title": "Порядок согласования",
                            "url": "https://example.com/order",
                            "description": "<strong>Согласование</strong> за 3 дня",
                            "page_age": "2026-10-28T09:00:00",
                        }
                    ]
                }
            },
        )

    adapter = BraveSearchAdapter(KEY, transport=_transport(handler))
    hits = await adapter.search(WebSearchRequest(query="согласование", recency_days=3, limit=5))
    await adapter.aclose()

    assert seen["q"] == "согласование"
    assert seen["freshness"] == "pw"
    assert seen["count"] == "5"
    assert len(hits) == 1
    assert hits[0].snippet == "Согласование за 3 дня"
    assert hits[0].published_at == datetime(2026, 10, 28, 9, 0, tzinfo=UTC)


async def test_brave_empty_results_are_not_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"query": "ничего"})

    adapter = BraveSearchAdapter(KEY, transport=_transport(handler))
    assert await adapter.search(WebSearchRequest(query="ничего")) == ()
    await adapter.aclose()


async def test_exa_search_parses_published_and_text() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.headers["x-api-key"] == KEY
        seen.update(json_body(request))
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Заявка на согласование",
                        "url": "https://example.com/request",
                        "publishedDate": "2026-10-29T12:30:00.000Z",
                        "text": "Сначала заявку проверяет руководитель",
                    }
                ]
            },
        )

    adapter = ExaSearchAdapter(KEY, transport=_transport(handler))
    hits = await adapter.search(WebSearchRequest(query="заявка", recency_days=14, limit=4))
    await adapter.aclose()

    assert seen["numResults"] == 4
    assert "startPublishedDate" in seen
    assert len(hits) == 1
    assert hits[0].snippet == "Сначала заявку проверяет руководитель"
    assert hits[0].published_at == datetime(2026, 10, 29, 12, 30, tzinfo=UTC)


async def test_jina_reader_returns_text_title_and_canonical() -> None:
    """Jina Reader отдаёт преамбулу с заголовком и исходным адресом — это `rel=canonical`."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == f"/{PAGE_URL}"
        assert request.headers["Authorization"] == f"Bearer {KEY}"
        return httpx.Response(
            200,
            text=(
                "Title: Согласование заявки\n\n"
                "URL Source: https://example.com/process?utm_campaign=test\n\n"
                "Markdown Content:\n# Согласование\n\nЗаявка уходит руководителю.\n"
            ),
        )

    adapter = JinaReaderAdapter(KEY, transport=_transport(handler), credential_id=None)
    page = await adapter.fetch(PAGE_URL)
    await adapter.aclose()

    assert page.title == "Согласование заявки"
    assert page.canonical_url == "https://example.com/process?utm_campaign=test"
    assert page.text == "# Согласование\n\nЗаявка уходит руководителю."
    assert page.fetched_at.tzinfo is not None
    assert page.url == PAGE_URL


async def test_jina_reader_without_preamble_keeps_whole_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, text="Просто текст страницы")

    adapter = JinaReaderAdapter(KEY, transport=_transport(handler))
    page = await adapter.fetch(PAGE_URL)
    await adapter.aclose()

    assert page.title is None
    assert page.canonical_url is None
    assert page.text == "Просто текст страницы"


async def test_firecrawl_returns_canonical_and_published_date() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1/scrape"
        body = json_body(request)
        assert body["url"] == PAGE_URL
        assert body["formats"] == ["markdown"]
        assert body["timeout"] == FIRECRAWL_PROVIDER_TIMEOUT_MS
        assert FIRECRAWL_PROVIDER_TIMEOUT_MS < WEB_REQUEST_TIMEOUT_SEC * 1000
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "markdown": "# Процесс\n\nЗаявка согласуется за три дня.",
                    "metadata": {
                        "title": "Процесс согласования",
                        "canonical": "https://example.com/process-canonical",
                        "publishedTime": "2026-10-27T08:00:00+03:00",
                    },
                },
            },
        )

    adapter = FirecrawlFetchAdapter(KEY, transport=_transport(handler))
    page = await adapter.fetch(PAGE_URL)
    await adapter.aclose()

    assert page.text == "# Процесс\n\nЗаявка согласуется за три дня."
    assert page.canonical_url == "https://example.com/process-canonical"
    assert page.published_at == datetime(2026, 10, 27, 5, 0, tzinfo=UTC)
    assert page.title == "Процесс согласования"


@pytest.mark.parametrize("name", ALL_PROVIDERS)
async def test_check_confirms_valid_key(name: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        if name == "jina":
            return httpx.Response(200, text="Title: t\n\nURL Source: u\n\nMarkdown Content:\nтекст")
        return httpx.Response(200, json={"results": [], "web": {"results": []}, "data": {}})

    adapter = _build(name, handler)
    detail = await adapter.check()
    await adapter.aclose()
    assert "действует" in detail


# --- Классы ошибок -------------------------------------------------------------------------

_RETRYABLE = pytest.mark.parametrize(
    ("status", "body", "expected", "retry_after"),
    [
        (429, "rate limit exceeded", ErrorClass.TRANSIENT, 7.0),
        (429, "insufficient_quota", ErrorClass.QUOTA_EXHAUSTED, 7.0),
        (401, "invalid api key", ErrorClass.AUTH, 7.0),
        (403, "forbidden", ErrorClass.AUTH, 7.0),
        (413, "too large", ErrorClass.UNSUPPORTED, 7.0),
        (500, "boom", ErrorClass.TRANSIENT, 7.0),
        (400, "bad request", ErrorClass.FATAL, 7.0),
    ],
)


@_RETRYABLE
@pytest.mark.parametrize("name", ALL_PROVIDERS)
async def test_provider_error_status_becomes_error_class(
    name: str, status: int, body: str, expected: ErrorClass, retry_after: float | None
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(status, text=body, headers={"Retry-After": "7"})

    adapter = _build(name, handler)
    with pytest.raises(CapabilityError) as info:
        await _invoke(adapter, name)
    await adapter.aclose()

    error = info.value
    assert error.error_class is expected
    assert error.retry_after_sec == retry_after
    # Текст провайдера в сообщение не попадает — только понятная причина.
    assert "rate limit" not in error.message.lower()
    assert "boom" not in error.message.lower()


@pytest.mark.parametrize("name", ALL_PROVIDERS)
async def test_provider_timeout_is_transient(name: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        raise httpx.ReadTimeout("timed out")

    adapter = _build(name, handler)
    with pytest.raises(CapabilityError) as info:
        await _invoke(adapter, name)
    await adapter.aclose()
    assert info.value.error_class is ErrorClass.TRANSIENT


@pytest.mark.parametrize("name", SEARCH_PROVIDERS)
async def test_broken_json_is_transient(name: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, text="не json")

    adapter = _build(name, handler)
    with pytest.raises(CapabilityError) as info:
        await _invoke(adapter, name)
    await adapter.aclose()
    assert info.value.error_class is ErrorClass.TRANSIENT


async def test_firecrawl_failed_scrape_is_unsupported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"success": True, "data": {"markdown": "  "}})

    adapter = FirecrawlFetchAdapter(KEY, transport=_transport(handler))
    with pytest.raises(CapabilityError) as info:
        await adapter.fetch(PAGE_URL)
    await adapter.aclose()
    assert info.value.error_class is ErrorClass.UNSUPPORTED


async def test_jina_empty_page_is_unsupported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, text="Title: t\n\nURL Source: u\n\nMarkdown Content:\n\n")

    adapter = JinaReaderAdapter(KEY, transport=_transport(handler))
    with pytest.raises(CapabilityError) as info:
        await adapter.fetch(PAGE_URL)
    await adapter.aclose()
    assert info.value.error_class is ErrorClass.UNSUPPORTED


async def test_response_size_limit_is_enforced() -> None:
    response = httpx.Response(
        200, content=b"x" * 100, request=httpx.Request("GET", "https://example.com")
    )
    with pytest.raises(CapabilityError) as info:
        await read_limited(response, max_bytes=10, provider_label="Тест")
    assert info.value.error_class is ErrorClass.UNSUPPORTED


async def test_content_length_limit_is_enforced_before_read() -> None:
    response = httpx.Response(
        200,
        headers={"Content-Length": "999999"},
        content=b"",
        request=httpx.Request("GET", "https://example.com"),
    )
    with pytest.raises(CapabilityError):
        await read_limited(response, max_bytes=10, provider_label="Тест")


def test_adapter_metadata() -> None:
    assert TavilySearchAdapter.capability is Capability.WEB_SEARCH
    assert BraveSearchAdapter.capability is Capability.WEB_SEARCH
    assert ExaSearchAdapter.capability is Capability.WEB_SEARCH
    assert JinaReaderAdapter.capability is Capability.WEB_FETCH
    assert FirecrawlFetchAdapter.capability is Capability.WEB_FETCH
    assert TavilySearchAdapter.provider == "tavily"
    assert JinaReaderAdapter.provider == "jina"


# --- Общие помощники -----------------------------------------------------------------------


def test_normalize_url_drops_tracking_and_fragment() -> None:
    assert (
        normalize_url("HTTPS://Example.COM/Path/?utm_source=x&id=1&gclid=y#top")
        == "https://example.com/Path/?id=1"
    )
    assert normalize_url("https://example.com") == "https://example.com/"
    assert normalize_url("ftp://example.com/file") is None
    assert normalize_url("javascript:alert(1)") is None
    # Логин и пароль в адресе отклоняются; строку собираем, чтобы secretlint не принял за секрет.
    auth_url = "https://" + "user" + ":" + "password" + "@example.com/"
    assert normalize_url(auth_url) is None
    assert normalize_url("") is None


def test_parse_published_handles_iso_and_rubbish() -> None:
    assert parse_published("2026-10-30") == datetime(2026, 10, 30, tzinfo=UTC)
    assert parse_published("2026-10-30T10:00:00Z") == datetime(2026, 10, 30, 10, 0, tzinfo=UTC)
    assert parse_published("2026-10-30T10:00:00+03:00") == datetime(2026, 10, 30, 7, 0, tzinfo=UTC)
    assert parse_published("два дня назад") is None
    assert parse_published(123) is None
    assert parse_published(None) is None


def test_clean_snippet_strips_tags_and_trims() -> None:
    assert clean_snippet("<b>Согласование</b>  заявки") == "Согласование заявки"
    assert len(clean_snippet("ы" * 1000)) == 400
    assert clean_snippet(None) == ""


def test_clamp_limit_bounds() -> None:
    assert clamp_limit(0) == 1
    assert clamp_limit(50) == 10
    assert clamp_limit(4) == 4


def test_dedupe_hits_keeps_one_per_address() -> None:
    hits = (
        WebSearchHit(url="https://example.com/a#x", title="A", snippet="1"),
        WebSearchHit(url="https://example.com/a", title="A копия", snippet="2"),
        WebSearchHit(url="https://example.com/b", title="B", snippet="3"),
    )
    result = dedupe_hits(hits, limit=5)
    # Дедупликация сравнивает нормализованные адреса, но отдаёт исходные.
    assert [hit.url for hit in result] == ["https://example.com/a#x", "https://example.com/b"]
    assert result[0].title == "A"


def json_body(request: httpx.Request) -> dict[str, object]:
    return json.loads(request.content)
