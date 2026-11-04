"""Контракты и общие правила адаптеров `web_search` и `web_fetch` (RFC-0006, шаг 6).

Результаты поиска и публичные страницы становятся источниками с `trust=external` и ссылкой с
датой: по ним можно цитировать, но ниже приоритетом при конфликте с материалами пользователя.
Закрытые системы (Confluence, порталы за логином) так не читаются: их закрывают внешние агенты
пользователя через MCP (RFC-0007).

Адаптер одного провайдера: проверка ключа (`check`) и рабочий вызов (`search`/`fetch`). Общие
правила одинаковы для всех: фиксированный адрес API, `client_factory`/транспорт из контекста
(ADR-0011), запрет редиректов, таймаут, предел размера ответа, класс ошибки и `Retry-After`
(`adapters/http.py`). Текст ответа провайдера наружу не уходит — только структурные поля.
"""

import json
import re
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from app.domain.capabilities import Capability, CapabilityError, ErrorClass
from app.ingest.adapters.base import CapabilityAdapter
from app.ingest.adapters.http import HTTP_ERROR_STATUS, provider_error

# Срок одного запроса к провайдеру: поиск и чтение страницы — интерактивные операции.
WEB_REQUEST_TIMEOUT_SEC = 30.0
# Сколько байт ответа читаем: JSON поиска небольшой, markdown страницы — крупнее.
MAX_SEARCH_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_PAGE_RESPONSE_BYTES = 8 * 1024 * 1024
# Пределы для модели: выдержка результата и число результатов на один запрос.
MAX_SNIPPET_CHARS = 400
MIN_RESULTS = 1
MAX_RESULTS = 10
# Предел длины ссылки результата: длиннее — почти наверняка мусор.
MAX_RESULT_URL_CHARS = 2_000

# Метки слежения не меняют страницу: при дедупликации они отбрасываются.
_HTML_TAG = re.compile(r"<[^>]*>")
_TRACKING_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "yclid",
        "gclid",
        "fbclid",
        "mc_cid",
        "mc_eid",
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class WebSearchRequest:
    """Поисковый запрос: формулировка, необязательная свежесть и предел выдачи."""

    query: str
    recency_days: int | None = None
    limit: int = 5


@dataclass(frozen=True, slots=True, kw_only=True)
class WebSearchHit:
    """Ссылка, выдержка и дата публикации — основание `trust=external`."""

    url: str
    title: str
    snippet: str
    published_at: datetime | None = None
    source: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class WebPage:
    """Прочитанная страница: текст, ссылка и дата получения (для провенанса).

    `canonical_url` — адрес из метаданных провайдера (аналог `rel=canonical`); если провайдер
    его не сообщил, `None` — вызывающий код берёт нормализованный запрошенный адрес.
    """

    url: str
    text: str
    fetched_at: datetime
    title: str | None = None
    canonical_url: str | None = None
    published_at: datetime | None = None


class WebSearchAdapter(CapabilityAdapter, Protocol):
    """`search_web(query, recency?)` — возможность `web_search`."""

    capability: Capability

    async def search(self, request: WebSearchRequest) -> tuple[WebSearchHit, ...]:
        """Ищет ссылки; класс ошибки — `CapabilityError`, пустая выдача допустима."""
        ...


class WebFetchAdapter(CapabilityAdapter, Protocol):
    """`read_url(url)` — возможность `web_fetch`."""

    capability: Capability

    async def fetch(self, url: str) -> WebPage:
        """Читает страницу; адрес проверяет сервис до вызова, не адаптер."""
        ...


def provider_headers(*, accept: str = "application/json", **extra: str) -> dict[str, str]:
    """Обычные заголовки провайдера; ключ добавляет адаптер и в сообщения не пишет."""
    return {"Accept": accept, "User-Agent": "BPMN.Space web tools", **extra}


async def read_limited(response: httpx.Response, *, max_bytes: int, provider_label: str) -> bytes:
    """Читает тело ответа целиком, но не больше предела: иначе — класс `unsupported`.

    Предел защищает память VPS от чужого сервера или огромной страницы. Проверяется и
    `Content-Length` (если провайдер его прислал), и фактический размер потока.
    """
    too_large = CapabilityError(
        ErrorClass.UNSUPPORTED, f"{provider_label} вернул ответ больше допустимого размера"
    )
    length = response.headers.get("Content-Length")
    if length is not None:
        try:
            if int(length) > max_bytes:
                raise too_large
        except ValueError:
            pass
    chunks: list[bytes] = []
    total = 0
    async for chunk in _chunks(response):
        total += len(chunk)
        if total > max_bytes:
            raise too_large
        chunks.append(chunk)
    return b"".join(chunks)


async def _chunks(response: httpx.Response) -> AsyncIterator[bytes]:
    async for chunk in response.aiter_bytes():
        yield chunk


async def request_json(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    provider_label: str,
    max_bytes: int = MAX_SEARCH_RESPONSE_BYTES,
    **kwargs: object,
) -> dict[str, object]:
    """Запрос провайдера с общими правилами: класс ошибки, лимит размера, разбор JSON.

    Таймаут и обрыв сети — `transient` (маршрутизатор повторит), ответ не по схеме — тоже:
    повтор обычно помогает, а разбирать тело провайдера пользователю не нужно.
    """
    try:
        async with client.stream(method, path, **kwargs) as response:  # type: ignore[arg-type]
            if response.status_code >= HTTP_ERROR_STATUS:
                raise await provider_error(response, provider_label=provider_label)
            raw = await read_limited(response, max_bytes=max_bytes, provider_label=provider_label)
    except (httpx.TimeoutException, httpx.TransportError):
        raise CapabilityError(
            ErrorClass.TRANSIENT, f"{provider_label} временно недоступен: повторите позже"
        ) from None
    return _json_object(raw, provider_label)


async def request_text(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    provider_label: str,
    max_bytes: int = MAX_PAGE_RESPONSE_BYTES,
    **kwargs: object,
) -> str:
    """Текстовый ответ провайдера (markdown страницы) с теми же правилами."""
    try:
        async with client.stream(method, path, **kwargs) as response:  # type: ignore[arg-type]
            if response.status_code >= HTTP_ERROR_STATUS:
                raise await provider_error(response, provider_label=provider_label)
            raw = await read_limited(response, max_bytes=max_bytes, provider_label=provider_label)
    except (httpx.TimeoutException, httpx.TransportError):
        raise CapabilityError(
            ErrorClass.TRANSIENT, f"{provider_label} временно недоступен: повторите позже"
        ) from None
    return raw.decode("utf-8", errors="replace")


def _json_object(raw: bytes, provider_label: str) -> dict[str, object]:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise CapabilityError(
            ErrorClass.TRANSIENT, f"{provider_label} вернул ответ в неизвестном формате"
        ) from None
    if not isinstance(data, dict):
        raise CapabilityError(
            ErrorClass.TRANSIENT, f"{provider_label} вернул ответ в неизвестном формате"
        )
    return data


def clamp_limit(limit: int) -> int:
    """Предел выдачи провайдера: не меньше одного и не больше `MAX_RESULTS`."""
    return max(MIN_RESULTS, min(int(limit), MAX_RESULTS))


def clean_snippet(value: object, *, max_chars: int = MAX_SNIPPET_CHARS) -> str:
    """Выдержка из ответа поиска: без HTML-тегов и лишних пробелов."""
    if not isinstance(value, str):
        return ""
    without_tags = _HTML_TAG.sub(" ", value)
    return " ".join(without_tags.split())[:max_chars]


def parse_published(value: object) -> datetime | None:
    """Дата публикации из ответа провайдера: ISO 8601 либо None (кривое поле не роняет поиск)."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.combine(date.fromisoformat(raw[:10]), datetime.min.time())
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def normalize_url(raw: object) -> str | None:
    """Ключ дедупликации ссылки: адрес результата без якоря и меток слежения.

    Наружу (в выдачу модели) уходит исходный адрес провайдера, а нормализованный адрес — только
    ключ: `None`, если это не http(s)-адрес.
    """
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if not value or len(value) > MAX_RESULT_URL_CHARS:
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None
    query = [
        (name, item)
        for name, item in parse_qsl(parsed.query, keep_blank_values=True)
        if name.lower() not in _TRACKING_PARAMS
    ]
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path or "/",
            urlencode(query),
            "",
        )
    )


def dedupe_hits(hits: Iterable[WebSearchHit], *, limit: int) -> tuple[WebSearchHit, ...]:
    """Ссылки без повторов, не больше `limit`; адрес в выдаче остаётся исходным.

    Нормализованный адрес — только ключ дедупликации: переписывать ссылки провайдера нельзя,
    иначе модель и провенанс получают адрес, которого в выдаче не было.
    """
    found: list[WebSearchHit] = []
    seen: set[str] = set()
    for hit in hits:
        key = normalize_url(hit.url)
        if key is None or key in seen:
            continue
        seen.add(key)
        found.append(hit)
        if len(found) >= limit:
            break
    return tuple(found)


__all__ = [
    "MAX_PAGE_RESPONSE_BYTES",
    "MAX_RESULTS",
    "MAX_SEARCH_RESPONSE_BYTES",
    "MAX_SNIPPET_CHARS",
    "WEB_REQUEST_TIMEOUT_SEC",
    "WebFetchAdapter",
    "WebPage",
    "WebSearchAdapter",
    "WebSearchHit",
    "WebSearchRequest",
    "clamp_limit",
    "clean_snippet",
    "dedupe_hits",
    "normalize_url",
    "parse_published",
    "provider_headers",
    "read_limited",
    "request_json",
    "request_text",
]
