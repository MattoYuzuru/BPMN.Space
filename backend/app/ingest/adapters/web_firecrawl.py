"""Firecrawl: страница → markdown через API провайдера по ключу пользователя (RFC-0006, шаг 6).

`POST {адрес}/v1/scrape` возвращает markdown, заголовок, дату публикации и канонический адрес
(`metadata.canonical`/`metadata.sourceURL`). Ключ передаётся заголовком `Authorization: Bearer`.
Проверка ключа — `GET /v1/team/credit-usage`: остаток кредитов, без расхода на чтение страниц.
"""

from datetime import UTC, datetime

import httpx

from app.domain.capabilities import Capability, CapabilityError, ErrorClass
from app.ingest.adapters.http import HTTP_ERROR_STATUS, provider_client, provider_error
from app.ingest.adapters.web import (
    MAX_PAGE_RESPONSE_BYTES,
    WEB_REQUEST_TIMEOUT_SEC,
    WebPage,
    parse_published,
    provider_headers,
    request_json,
)

FIRECRAWL_BASE_URL = "https://api.firecrawl.dev"
_PROVIDER_LABEL = "Firecrawl"
# Таймаут задания у провайдера меньше клиентского (30 с) с запасом: Firecrawl успевает вернуть
# понятную ошибку, а не оборвать соединение. После таймаута маршрутизатор может повторить
# запрос, и повтор не должен оплачивать кредит за уже отменённое задание.
FIRECRAWL_PROVIDER_TIMEOUT_MS = 20_000


class FirecrawlFetchAdapter:
    """Ключ Firecrawl: `provider=firecrawl`, чтение страницы в markdown."""

    capability = Capability.WEB_FETCH
    provider = "firecrawl"
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
            base_url=FIRECRAWL_BASE_URL,
            timeout_sec=min(timeout_sec, WEB_REQUEST_TIMEOUT_SEC),
            transport=transport,
            client_factory=client_factory,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def check(self) -> str:
        """Остаток кредитов аккаунта: проверка ключа не тратит кредиты на чтение страниц."""
        try:
            response = await self._http.get(
                "/v1/team/credit-usage",
                headers=provider_headers(
                    Authorization=f"Bearer {self._api_key}",
                ),
            )
        except (httpx.TimeoutException, httpx.TransportError):
            raise CapabilityError(
                ErrorClass.TRANSIENT,
                f"{_PROVIDER_LABEL} временно недоступен: повторите позже",
            ) from None
        if response.status_code >= HTTP_ERROR_STATUS:
            raise await provider_error(response, provider_label=_PROVIDER_LABEL)
        return "Ключ Firecrawl действует"

    async def fetch(self, url: str) -> WebPage:
        data = await request_json(
            self._http,
            "POST",
            "/v1/scrape",
            provider_label=_PROVIDER_LABEL,
            max_bytes=MAX_PAGE_RESPONSE_BYTES,
            json={
                "url": url,
                "formats": ["markdown"],
                "onlyMainContent": True,
                "timeout": FIRECRAWL_PROVIDER_TIMEOUT_MS,
            },
            headers=provider_headers(
                Authorization=f"Bearer {self._api_key}",
            ),
        )
        payload = data.get("data")
        if not isinstance(payload, dict):
            raise CapabilityError(
                ErrorClass.TRANSIENT, f"{_PROVIDER_LABEL} вернул ответ в неизвестном формате"
            )
        text = payload.get("markdown")
        if not isinstance(text, str) or not text.strip():
            raise CapabilityError(
                ErrorClass.UNSUPPORTED, "Firecrawl не смог прочитать текст страницы"
            )
        metadata = payload.get("metadata")
        meta = metadata if isinstance(metadata, dict) else {}
        return WebPage(
            url=url,
            text=text.strip(),
            fetched_at=datetime.now(UTC),
            title=_text(meta.get("title")),
            canonical_url=_text(meta.get("canonical")) or _text(meta.get("sourceURL")) or None,
            published_at=_published(meta),
        )


def _published(metadata: dict[str, object]) -> datetime | None:
    """Дата публикации из метаданных Firecrawl (поле `publishedTime` ISO 8601)."""
    return parse_published(metadata.get("publishedTime") or metadata.get("published_time"))


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


__all__ = ["FIRECRAWL_BASE_URL", "FIRECRAWL_PROVIDER_TIMEOUT_MS", "FirecrawlFetchAdapter"]
