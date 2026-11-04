"""Tavily: поиск для агентов по ключу пользователя (RFC-0006, шаг 6).

`POST {адрес}/search` отвечает заголовками, ссылками, выдержками и (не всегда) датой публикации.
Ключ передаётся заголовком `Authorization: Bearer`. Проверка ключа — тот же поиск с одним
результатом: отдельного бесплатного эндпоинта у провайдера нет, поэтому проверка стоит один
кредит из бесплатных 1000 в месяц.
"""

import httpx

from app.domain.capabilities import Capability, CapabilityError, ErrorClass
from app.ingest.adapters.http import provider_client
from app.ingest.adapters.web import (
    MAX_SEARCH_RESPONSE_BYTES,
    WEB_REQUEST_TIMEOUT_SEC,
    WebSearchHit,
    WebSearchRequest,
    clamp_limit,
    clean_snippet,
    dedupe_hits,
    parse_published,
    provider_headers,
    request_json,
)

TAVILY_BASE_URL = "https://api.tavily.com"
_PROVIDER_LABEL = "Tavily"
_CHECK_QUERY = "проверка ключа"
# Tavily принимает окно свежести словом; `days` работает только с topic=news.
_TIME_RANGE_STEPS: tuple[tuple[int, str], ...] = ((1, "day"), (7, "week"), (31, "month"))


class TavilySearchAdapter:
    """Ключ Tavily: `provider=tavily`, поиск по смыслу с датами публикации."""

    capability = Capability.WEB_SEARCH
    provider = "tavily"
    model: str | None = None

    def __init__(
        self,
        api_key: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        client_factory=None,
        timeout_sec: float = WEB_REQUEST_TIMEOUT_SEC,
        credential_id=None,
    ) -> None:
        self._api_key = api_key
        self.credential_id = credential_id
        self._http = provider_client(
            base_url=TAVILY_BASE_URL,
            timeout_sec=min(timeout_sec, WEB_REQUEST_TIMEOUT_SEC),
            transport=transport,
            client_factory=client_factory,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def check(self) -> str:
        """Дешёвый поиск с одним результатом: подтверждает ключ и доступ к API."""
        await self._search({"query": _CHECK_QUERY, "max_results": 1})
        return "Ключ Tavily действует"

    async def search(self, request: WebSearchRequest) -> tuple[WebSearchHit, ...]:
        body: dict[str, object] = {
            "query": request.query,
            "max_results": clamp_limit(request.limit),
            "search_depth": "basic",
            "include_answer": False,
            "include_raw_content": False,
        }
        time_range = _time_range(request.recency_days)
        if time_range is not None:
            body["time_range"] = time_range
        data = await self._search(body)
        results = data.get("results")
        if not isinstance(results, list):
            raise CapabilityError(
                ErrorClass.TRANSIENT, f"{_PROVIDER_LABEL} вернул ответ в неизвестном формате"
            )
        hits: list[WebSearchHit] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            hits.append(
                WebSearchHit(
                    url=_text(item.get("url")),
                    title=_text(item.get("title")),
                    snippet=clean_snippet(item.get("content")),
                    published_at=parse_published(item.get("published_date")),
                    source=self.provider,
                )
            )
        return dedupe_hits(
            (hit for hit in hits if hit.url and hit.title),
            limit=clamp_limit(request.limit),
        )

    async def _search(self, body: dict[str, object]) -> dict[str, object]:
        return await request_json(
            self._http,
            "POST",
            "/search",
            provider_label=_PROVIDER_LABEL,
            max_bytes=MAX_SEARCH_RESPONSE_BYTES,
            json=body,
            headers=provider_headers(
                Authorization=f"Bearer {self._api_key}",
            ),
        )


def _time_range(recency_days: int | None) -> str | None:
    """Окно свежести Tavily: сутки, неделя, месяц или год."""
    if recency_days is None:
        return None
    for days, value in _TIME_RANGE_STEPS:
        if recency_days <= days:
            return value
    return "year"


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


__all__ = ["TAVILY_BASE_URL", "TavilySearchAdapter"]
