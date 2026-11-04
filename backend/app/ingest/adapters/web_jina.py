"""Jina Reader: страница → markdown по ключу пользователя (RFC-0006, шаг 6).

`GET https://r.jina.ai/<адрес>` возвращает текст страницы с преамбулой `Title:`, `URL Source:`
и `Markdown Content:`. Без ключа работает 20 запросов в минуту, с ключом — 500 в минуту и
10 млн токенов бесплатно; ключ передаётся заголовком `Authorization: Bearer`. Сервер сам
страницу не скачивает: адрес проверяет сервис, читает провайдер, поэтому SSRF-правила
(ADR-0011) применяются к адресу, а транспорт — только к `r.jina.ai`.
"""

from datetime import UTC, datetime

import httpx

from app.domain.capabilities import Capability, CapabilityError, ErrorClass
from app.ingest.adapters.http import provider_client
from app.ingest.adapters.web import (
    MAX_PAGE_RESPONSE_BYTES,
    WEB_REQUEST_TIMEOUT_SEC,
    WebPage,
    provider_headers,
    request_text,
)

JINA_READER_BASE_URL = "https://r.jina.ai"
_PROVIDER_LABEL = "Jina Reader"
# Небольшая стабильная страница для проверки ключа: текст читается за один запрос.
_CHECK_URL = "https://example.com"
_MARKDOWN_MARKER = "Markdown Content:"


class JinaReaderAdapter:
    """Ключ Jina Reader: `provider=jina`, чтение публичной страницы в markdown."""

    capability = Capability.WEB_FETCH
    provider = "jina"
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
            base_url=JINA_READER_BASE_URL,
            timeout_sec=min(timeout_sec, WEB_REQUEST_TIMEOUT_SEC),
            transport=transport,
            client_factory=client_factory,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def check(self) -> str:
        """Чтение известной страницы: подтверждает ключ и доступ к Reader."""
        await self._read(_CHECK_URL)
        return "Ключ Jina Reader действует"

    async def fetch(self, url: str) -> WebPage:
        text = await self._read(url)
        title, canonical, body = split_reader_output(text)
        if not body:
            raise CapabilityError(ErrorClass.UNSUPPORTED, "Jina Reader не вернул текст страницы")
        return WebPage(
            url=url,
            text=body,
            fetched_at=datetime.now(UTC),
            title=title,
            canonical_url=canonical,
        )

    async def _read(self, url: str) -> str:
        return await request_text(
            self._http,
            "GET",
            f"/{url}",
            provider_label=_PROVIDER_LABEL,
            max_bytes=MAX_PAGE_RESPONSE_BYTES,
            headers=provider_headers(
                accept="text/plain",
                **{"X-Return-Format": "markdown"},
                Authorization=f"Bearer {self._api_key}",
            ),
        )


def split_reader_output(text: str) -> tuple[str | None, str | None, str]:
    """Разбирает преамбулу Reader: заголовок, исходный адрес и текст после неё.

    Если преамбулы нет (например, её выключили заголовком), весь ответ считается текстом.
    """
    head, marker, rest = text.partition(_MARKDOWN_MARKER)
    if not marker:
        return None, None, text.strip()
    title: str | None = None
    canonical: str | None = None
    for line in head.splitlines():
        name, _, value = line.partition(":")
        key = name.strip().lower()
        if key == "title":
            title = value.strip() or None
        elif key == "url source":
            canonical = value.strip() or None
    return title, canonical, rest.strip()


__all__ = ["JINA_READER_BASE_URL", "JinaReaderAdapter", "split_reader_output"]
