"""Exa: поиск по смыслу и содержимое страниц по ключу пользователя (RFC-0006, шаг 6).

`POST {адрес}/search` принимает запрос и возвращает `results[]` с заголовком, адресом,
датой публикации и (если попросить) коротким текстом. Ключ передаётся заголовком `x-api-key`.
Проверка ключа — поиск с одним результатом без содержимого страниц.
"""

from datetime import UTC, datetime, timedelta

import httpx

from app.domain.capabilities import Capability, CapabilityError, ErrorClass
from app.ingest.adapters.http import provider_client
from app.ingest.adapters.web import (
    MAX_SEARCH_RESPONSE_BYTES,
    MAX_SNIPPET_CHARS,
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

EXA_BASE_URL = "https://api.exa.ai"
_PROVIDER_LABEL = "Exa"
_CHECK_QUERY = "проверка ключа"


class ExaSearchAdapter:
    """Ключ Exa: `provider=exa`, семантический поиск с датами и коротким текстом."""

    capability = Capability.WEB_SEARCH
    provider = "exa"
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
            base_url=EXA_BASE_URL,
            timeout_sec=min(timeout_sec, WEB_REQUEST_TIMEOUT_SEC),
            transport=transport,
            client_factory=client_factory,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def check(self) -> str:
        """Поиск одного результата без содержимого страниц: дешёвая проверка ключа."""
        await self._search({"query": _CHECK_QUERY, "numResults": 1})
        return "Ключ Exa действует"

    async def search(self, request: WebSearchRequest) -> tuple[WebSearchHit, ...]:
        limit = clamp_limit(request.limit)
        body: dict[str, object] = {
            "query": request.query,
            "numResults": limit,
            "type": "auto",
            # Короткий текст нужен для выдержки; без него результаты приходят без описания.
            "contents": {"text": {"maxCharacters": MAX_SNIPPET_CHARS}},
        }
        start = _start_published(request.recency_days)
        if start is not None:
            body["startPublishedDate"] = start
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
                    snippet=clean_snippet(item.get("text")),
                    published_at=parse_published(item.get("publishedDate")),
                    source=self.provider,
                )
            )
        return dedupe_hits(
            (hit for hit in hits if hit.url and hit.title),
            limit=limit,
        )

    async def _search(self, body: dict[str, object]) -> dict[str, object]:
        return await request_json(
            self._http,
            "POST",
            "/search",
            provider_label=_PROVIDER_LABEL,
            max_bytes=MAX_SEARCH_RESPONSE_BYTES,
            json=body,
            headers=provider_headers(**{"x-api-key": self._api_key}),
        )


def _start_published(recency_days: int | None) -> str | None:
    """Начало окна свежести Exa: ISO 8601 в UTC или None."""
    if recency_days is None:
        return None
    start = datetime.now(UTC) - timedelta(days=recency_days)
    return start.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


__all__ = ["EXA_BASE_URL", "ExaSearchAdapter"]
