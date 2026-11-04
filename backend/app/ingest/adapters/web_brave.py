"""Brave Search API: собственный индекс, поиск по ключу пользователя (RFC-0006, шаг 6).

`GET {адрес}/res/v1/web/search` отдаёт `web.results[]` с заголовком, адресом, описанием и
(иногда) ISO-датой `page_age`. Ключ передаётся заголовком `X-Subscription-Token`; карта у
провайдера обязательна. Проверка ключа — поиск с одним результатом.
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

BRAVE_BASE_URL = "https://api.search.brave.com"
_PROVIDER_LABEL = "Brave Search"
_CHECK_QUERY = "проверка ключа"

# Свежесть Brave задаётся словом, а не числом дней: берём ближайший понятный интервал.
_FRESHNESS_STEPS: tuple[tuple[int, str], ...] = ((1, "pd"), (7, "pw"), (31, "pm"))
# Brave не принимает слово «год» длиннее: дальше считаем свежесть годом, а больше года — отказ.
_MAX_FRESHNESS_DAYS = 365


class BraveSearchAdapter:
    """Ключ Brave Search: `provider=brave`, собственный поисковый индекс."""

    capability = Capability.WEB_SEARCH
    provider = "brave"
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
            base_url=BRAVE_BASE_URL,
            timeout_sec=min(timeout_sec, WEB_REQUEST_TIMEOUT_SEC),
            transport=transport,
            client_factory=client_factory,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def check(self) -> str:
        await self._search({"q": _CHECK_QUERY, "count": 1})
        return "Ключ Brave Search действует"

    async def search(self, request: WebSearchRequest) -> tuple[WebSearchHit, ...]:
        limit = clamp_limit(request.limit)
        params: dict[str, object] = {
            "q": request.query,
            "count": limit,
            "text_decorations": "false",
            "safesearch": "moderate",
        }
        freshness = _freshness(request.recency_days)
        if freshness is not None:
            params["freshness"] = freshness
        data = await self._search(params)
        payload = data.get("web")
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            # Пустая выдача законна: Brave не отдаёт `web`, когда ничего не найдено.
            return ()
        hits: list[WebSearchHit] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            hits.append(
                WebSearchHit(
                    url=_text(item.get("url")),
                    title=_text(item.get("title")),
                    snippet=clean_snippet(item.get("description")),
                    published_at=parse_published(item.get("page_age")),
                    source=self.provider,
                )
            )
        return dedupe_hits(
            (hit for hit in hits if hit.url and hit.title),
            limit=limit,
        )

    async def _search(self, params: dict[str, object]) -> dict[str, object]:
        return await request_json(
            self._http,
            "GET",
            "/res/v1/web/search",
            provider_label=_PROVIDER_LABEL,
            max_bytes=MAX_SEARCH_RESPONSE_BYTES,
            params=params,
            headers=provider_headers(
                **{"X-Subscription-Token": self._api_key},
            ),
        )


def _freshness(recency_days: int | None) -> str | None:
    """Ближайший интервал свежести Brave: сутки, неделя, месяц или год."""
    if recency_days is None:
        return None
    for days, value in _FRESHNESS_STEPS:
        if recency_days <= days:
            return value
    if recency_days <= _MAX_FRESHNESS_DAYS:
        return "py"
    raise CapabilityError(ErrorClass.UNSUPPORTED, "Свежесть больше года не поддерживается поиском")


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


__all__ = ["BRAVE_BASE_URL", "BraveSearchAdapter"]
