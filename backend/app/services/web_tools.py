"""Веб-инструменты агентного режима (RFC-0006, шаг 6): `search_web` и `read_url`.

Модель просит «найди, что регламент говорит о согласовании» или «прочитай эту страницу», а не
«вызови Tavily»: возможность `web_search`/`web_fetch` закрывает любой подключённый ключ, выбор
делает существующий `CapabilityRouter` (приоритет, классы ошибок, предохранитель, `Retry-After`).

Сервис возвращает **структурный результат**: датированные ссылки с выдержками и прочитанный
текст страницы с каноническим адресом и датой получения. Это кандидаты в производные источники
`origin=derived`, `trust=external` (узел создаёт агентный режим, RFC-0004); сам сервис проект
не меняет. Если возможность недоступна, результат сохраняет класс причины и прогресс, а
`CapabilityIncidentSink` (волна 2B) создаёт неблокирующий технический вопрос проекта.

Кеш живёт в памяти прогона (`WebToolsCache`): повторный запрос не платит провайдеру дважды, а
повторяющиеся ссылки между запросами отбрасываются. Это не кеш производных источников из
RFC-0006: тот появится вместе с узлами дерева материалов.
"""

import ipaddress
import logging
import socket
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

from app.domain.capabilities import (
    Capability,
    CapabilityError,
    CapabilityIncident,
    CapabilityIncidentSink,
    CapabilityOutcome,
    CapabilityUnavailableError,
    ErrorClass,
)
from app.domain.models import SourceOrigin, SourceTrust
from app.ingest.adapters.web import (
    WebPage,
    WebSearchHit,
    WebSearchRequest,
    normalize_url,
)
from app.llm.net_guard import is_public_ip
from app.services.capability_router import CapabilityRouter
from app.services.common import Runtime
from app.services.errors import InvalidInputError

logger = logging.getLogger(__name__)

MAX_QUERY_CHARS = 500
MAX_URL_CHARS = 2_000
MIN_RESULTS = 1
MAX_RESULTS = 10
DEFAULT_RESULTS = 5
MAX_RECENCY_DAYS = 365
# Сколько символов страницы отдаём модели: остальное отбрасывается с пометкой `truncated`.
MAX_PAGE_CHARS = 200_000
# Пределы кеша прогона: прогон не должен расти безгранично из-за инструментов.
MAX_CACHED_SEARCHES = 32
MAX_CACHED_PAGES = 32

# Закрытые имена: локальные и служебные адреса не отправляем провайдеру даже как ссылку.
_BLOCKED_HOSTS = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "ip6-localhost",
        "metadata",
        "metadata.google.internal",
        "instance-data",
    }
)
_BLOCKED_HOST_SUFFIXES = (
    ".localhost",
    ".local",
    ".localdomain",
    ".internal",
    ".home",
    ".lan",
    ".corp",
)
_ALLOWED_PAGE_SCHEMES = frozenset({"http", "https"})
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


def checked_query(query: str) -> str:
    """Поисковая формулировка: непустая строка в пределах `MAX_QUERY_CHARS`."""
    value = (query or "").strip()
    if not value:
        raise InvalidInputError("Поисковый запрос не может быть пустым")
    if len(value) > MAX_QUERY_CHARS:
        raise InvalidInputError(
            f"Поисковый запрос длиннее {MAX_QUERY_CHARS} символов: сократите его"
        )
    return value


def checked_recency(recency_days: int | None) -> int | None:
    """Свежесть выдачи: целое число дней от 1 до `MAX_RECENCY_DAYS` или None."""
    if recency_days is None:
        return None
    days = int(recency_days)
    if not 1 <= days <= MAX_RECENCY_DAYS:
        raise InvalidInputError(f"Свежесть задаётся числом дней от 1 до {MAX_RECENCY_DAYS}")
    return days


def checked_limit(limit: int) -> int:
    """Предел выдачи: не меньше одного и не больше `MAX_RESULTS`."""
    return max(MIN_RESULTS, min(int(limit), MAX_RESULTS))


def _looks_numeric_host(host: str) -> bool:
    """Похож ли хост на нестандартную числовую запись IPv4 (2130706433, 0x7f…, 0177…).

    Такие записи разные библиотеки и сервисы понимают по-разному — это классический приём
    обхода SSRF-проверки: `ipaddress` видит домен, а `inet_aton`/браузер провайдера — loopback.
    """
    labels = host.split(".")
    if all(label.isdigit() for label in labels):
        return True  # целое число (2130706433) и короткая запись (127.1)
    if host.lower().startswith("0x"):
        return True
    for label in labels:
        lowered = label.lower()
        if lowered.startswith("0x"):
            return True
        if label.isdigit() and len(label) > 1 and label.startswith("0"):
            return True
    return False


def _numeric_host_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """IP-адрес хоста, включая нестандартные записи IPv4, которые понимает `inet_aton`.

    `ipaddress` принимает только каноническую запись, поэтому целое число (`2130706433`),
    hex (`0x7f000001`), короткая (`127.1`) и восьмеричная (`0177.0.0.1`) формы иначе остались
    бы «доменом» и ушли провайдеру.
    """
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    if not _looks_numeric_host(host):
        return None
    try:
        return ipaddress.ip_address(socket.inet_aton(host))
    except OSError:
        return None


def checked_page_url(raw: str) -> str:
    """Адрес страницы для `read_url`: только публичный http(s) без логина и служебных имён.

    Сервер не скачивает страницу сам (это делает провайдер по ключу), но закрытые адреса
    отклоняются до вызова: незачем отправлять чужому сервису `localhost`, приватные диапазоны и
    метаданные облака. Проверка литералов (127.0.0.1, 10.x, 169.254.169.254, [::1]) — та же,
    что в SSRF-защите моделей (ADR-0011). Нестандартные числовые формы IPv4 (`2130706433`,
    `0x7f000001`, `127.1`, `0177.0.0.1`) нормализуются через `inet_aton` и отклоняются, если
    указывают на закрытую сеть; в остальных случаях такие формы тоже запрещены — парсер
    провайдера может понять их иначе.
    """
    value = (raw or "").strip()
    if not value:
        raise InvalidInputError("Укажите адрес страницы")
    if len(value) > MAX_URL_CHARS:
        raise InvalidInputError("Адрес страницы слишком длинный")
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower().rstrip(".")
    except ValueError:
        raise InvalidInputError("Некорректный адрес страницы") from None
    if parsed.scheme.lower() not in _ALLOWED_PAGE_SCHEMES or not host:
        raise InvalidInputError("Адрес страницы должен начинаться с http:// или https://")
    if parsed.username or parsed.password:
        raise InvalidInputError("В адресе страницы не должно быть логина и пароля")
    if host in _BLOCKED_HOSTS or host.endswith(_BLOCKED_HOST_SUFFIXES):
        raise InvalidInputError(
            "Закрытые адреса читать нельзя: укажите публичную страницу, а материалы "
            "за логином приносит внешний агент (RFC-0007)"
        )
    literal = _numeric_host_ip(host)
    if literal is not None and not is_public_ip(literal):
        raise InvalidInputError(
            "Адрес страницы указывает на закрытую сеть: укажите публичную страницу"
        )
    if _looks_numeric_host(host):
        raise InvalidInputError(
            "Числовые формы адреса (целое число, 16-ричная запись, ведущие нули) не "
            "принимаются: укажите обычное имя или канонический IP"
        )
    return value


def provider_canonical_url(candidate: str | None, fallback: str) -> str:
    """Канонический адрес из метаданных провайдера; недопустимый — отказ, а не подмена.

    Если провайдер сообщил закрытый или битый адрес, текст страницы отдавать нельзя: провенанс
    производного источника должен вести на публичный адрес, а не на внутреннюю сеть или
    метаданные облака. Поэтому сервис возвращает структурный отказ без текста.
    """
    if candidate is None or not candidate.strip():
        return canonical_page_url(fallback)
    try:
        checked = checked_page_url(candidate)
    except InvalidInputError:
        raise CapabilityError(
            ErrorClass.FATAL,
            "Провайдер вернул недопустимый канонический адрес страницы: текст не принят",
        ) from None
    return canonical_page_url(checked)


def canonical_page_url(raw: str) -> str:
    """Нормализованный адрес страницы: без якоря и меток слежения.

    Аналог `rel=canonical`, если провайдер свой адрес не сообщил: запрос страницы и её
    канонический адрес должны совпадать у одной и той же страницы.
    """
    parsed = urlsplit(raw.strip())
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


@dataclass(frozen=True, slots=True, kw_only=True)
class WebSearchItem:
    """Один результат поиска: ссылка, выдержка, дата — основание `trust=external`."""

    title: str
    url: str
    snippet: str
    published_at: datetime | None = None
    source: str = ""
    trust: SourceTrust = SourceTrust.EXTERNAL
    origin: SourceOrigin = SourceOrigin.DERIVED

    def to_json(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "source": self.source,
            "trust": self.trust.value,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class WebSearchResult:
    """Структурный итог `search_web`: статус, ссылки и причина отказа без текста провайдера."""

    query: str
    status: str
    results: tuple[WebSearchItem, ...] = ()
    provider: str | None = None
    reason: str | None = None
    message: str | None = None
    alternatives: tuple[str, ...] = ()
    cached: bool = False
    outcome: CapabilityOutcome | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_json(self) -> dict[str, Any]:
        """Результат для модели и `derivation.params.routing` (RFC-0006)."""
        payload: dict[str, Any] = {
            "status": self.status,
            "query": self.query,
            "results": [item.to_json() for item in self.results],
            "provider": self.provider,
            "cached": self.cached,
        }
        _merge_outcome(payload, self.outcome, self.reason, self.message, self.alternatives)
        return payload


@dataclass(frozen=True, slots=True, kw_only=True)
class WebPageResult:
    """Структурный итог `read_url`: текст, канонический адрес, дата получения и причина отказа."""

    status: str
    url: str
    canonical_url: str
    text: str = ""
    title: str | None = None
    published_at: datetime | None = None
    fetched_at: datetime | None = None
    provider: str | None = None
    truncated: bool = False
    cached: bool = False
    trust: SourceTrust = SourceTrust.EXTERNAL
    origin: SourceOrigin = SourceOrigin.DERIVED
    reason: str | None = None
    message: str | None = None
    alternatives: tuple[str, ...] = ()
    outcome: CapabilityOutcome | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "url": self.url,
            "canonical_url": self.canonical_url,
            "title": self.title,
            "text": self.text,
            "published_at": self.published_at.isoformat()
            if self.published_at is not None
            else None,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at is not None else None,
            "provider": self.provider,
            "truncated": self.truncated,
            "cached": self.cached,
            "trust": self.trust.value,
        }
        _merge_outcome(payload, self.outcome, self.reason, self.message, self.alternatives)
        return payload


def _merge_outcome(
    payload: dict[str, Any],
    outcome: CapabilityOutcome | None,
    reason: str | None,
    message: str | None,
    alternatives: tuple[str, ...],
) -> None:
    """Добавляет к результату класс причины, прогресс и альтернативы (RFC-0006)."""
    payload["reason"] = reason
    payload["message"] = message
    payload["alternatives"] = list(alternatives)
    if outcome is not None:
        payload["routing"] = outcome.to_json()
        payload["done"] = outcome.done
        payload["remaining"] = outcome.remaining


@dataclass(slots=True)
class WebToolsCache:
    """Кеш прогона: поиски по запросу, прочитанные страницы и уже показанные ссылки."""

    searches: dict[tuple[str, int | None, int], WebSearchResult] = field(default_factory=dict)
    pages: dict[str, WebPageResult] = field(default_factory=dict)
    seen_urls: set[str] = field(default_factory=set)

    def remember_hits(self, hits: list[WebSearchItem]) -> list[WebSearchItem]:
        """Убирает ссылки, уже показанные в этом прогоне, и запоминает новые."""
        fresh: list[WebSearchItem] = []
        for hit in hits:
            url = normalize_url(hit.url)
            key = url or hit.url
            if key in self.seen_urls:
                continue
            self.seen_urls.add(key)
            fresh.append(hit)
        return fresh

    def put_search(self, key: tuple[str, int | None, int], result: WebSearchResult) -> None:
        if len(self.searches) >= MAX_CACHED_SEARCHES:
            self.searches.pop(next(iter(self.searches)))
        self.searches[key] = result

    def put_page(self, key: str, page: WebPageResult) -> None:
        if len(self.pages) >= MAX_CACHED_PAGES:
            self.pages.pop(next(iter(self.pages)))
        self.pages[key] = page


class WebTools:
    """Веб-возможности на ключах пользователя: поиск и чтение страниц для агентного режима."""

    def __init__(
        self,
        router: CapabilityRouter,
        *,
        incident_sink: CapabilityIncidentSink | None = None,
        runtime: Runtime | None = None,
    ) -> None:
        self._router = router
        self._sink = incident_sink
        self._rt = runtime or Runtime()

    def session(
        self,
        *,
        user_id: UUID | None,
        project_id: UUID | None = None,
        cache: WebToolsCache | None = None,
    ) -> "WebToolsSession":
        """Инструменты одного прогона: общий кеш и привязка к пользователю и проекту."""
        return WebToolsSession(
            self,
            user_id=user_id,
            project_id=project_id,
            cache=cache or WebToolsCache(),
        )

    async def search_web(
        self,
        *,
        user_id: UUID | None,
        query: str,
        recency_days: int | None = None,
        limit: int = DEFAULT_RESULTS,
        cache: WebToolsCache | None = None,
        project_id: UUID | None = None,
    ) -> WebSearchResult:
        """Ищет датированные ссылки по запросу; отказ — структурный результат, а не исключение."""
        text = checked_query(query)
        recency = checked_recency(recency_days)
        count = checked_limit(limit)
        key = (text.casefold(), recency, count)
        if cache is not None and key in cache.searches:
            return replace(cache.searches[key], cached=True)
        provider: dict[str, str] = {}

        async def invoke(adapter: Any) -> tuple[WebSearchHit, ...]:
            provider["used"] = getattr(adapter, "provider", "")
            return await adapter.search(
                WebSearchRequest(query=text, recency_days=recency, limit=count)
            )

        try:
            hits = await self._router.run(
                user_id=user_id,
                capability=Capability.WEB_SEARCH,
                invoke=invoke,
                progress=None,
            )
        except CapabilityUnavailableError as error:
            failure = self._search_failure(text, error.outcome)
            await self._report(project_id, Capability.WEB_SEARCH, error.outcome)
            return failure
        items = [
            WebSearchItem(
                title=hit.title,
                url=hit.url,
                snippet=hit.snippet,
                published_at=hit.published_at,
                source=hit.source or provider.get("used", ""),
            )
            for hit in hits[:count]
        ]
        if cache is not None:
            items = cache.remember_hits(items)
        result = WebSearchResult(
            query=text,
            status="ok",
            results=tuple(items),
            provider=provider.get("used") or None,
        )
        if cache is not None:
            cache.put_search(key, result)
        return result

    async def read_url(
        self,
        *,
        user_id: UUID | None,
        url: str,
        cache: WebToolsCache | None = None,
        project_id: UUID | None = None,
    ) -> WebPageResult:
        """Читает публичную страницу; адрес проверяется до вызова провайдера (SSRF)."""
        requested = checked_page_url(url)
        canonical = canonical_page_url(requested)
        if cache is not None and canonical in cache.pages:
            return replace(cache.pages[canonical], cached=True)
        provider: dict[str, str] = {}

        async def invoke(adapter: Any) -> WebPage:
            provider["used"] = getattr(adapter, "provider", "")
            return await adapter.fetch(requested)

        try:
            page = await self._router.run(
                user_id=user_id,
                capability=Capability.WEB_FETCH,
                invoke=invoke,
                progress=None,
            )
        except CapabilityUnavailableError as error:
            failure = self._page_failure(requested, canonical, error.outcome)
            await self._report(project_id, Capability.WEB_FETCH, error.outcome)
            return failure
        body = page.text if isinstance(page.text, str) else ""
        try:
            canonical_url = provider_canonical_url(page.canonical_url, page.url)
        except CapabilityError as error:
            # Провайдер ушёл на закрытый адрес: текст не принимаем, возвращаем структурный отказ.
            outcome = CapabilityOutcome(
                capability=Capability.WEB_FETCH,
                status="failed",
                reason=error.error_class.value,
                provider=provider.get("used") or None,
                message=error.message,
            )
            await self._report(project_id, Capability.WEB_FETCH, outcome)
            return self._page_failure(requested, canonical, outcome)
        truncated = len(body) > MAX_PAGE_CHARS
        result = WebPageResult(
            status="ok",
            url=requested,
            canonical_url=canonical_url,
            text=body[:MAX_PAGE_CHARS],
            title=page.title,
            published_at=page.published_at,
            fetched_at=self._rt.clock(),
            provider=provider.get("used") or None,
            truncated=truncated,
        )
        if cache is not None:
            cache.put_page(canonical, result)
        return result

    @staticmethod
    def _search_failure(query: str, outcome: CapabilityOutcome) -> WebSearchResult:
        return WebSearchResult(
            query=query,
            status=outcome.status,
            provider=outcome.provider,
            reason=outcome.reason,
            message=outcome.message,
            alternatives=outcome.alternatives,
            outcome=outcome,
        )

    @staticmethod
    def _page_failure(url: str, canonical: str, outcome: CapabilityOutcome) -> WebPageResult:
        return WebPageResult(
            status=outcome.status,
            url=url,
            canonical_url=canonical,
            provider=outcome.provider,
            reason=outcome.reason,
            message=outcome.message,
            alternatives=outcome.alternatives,
            outcome=outcome,
        )

    async def _report(
        self, project_id: UUID | None, capability: Capability, outcome: CapabilityOutcome
    ) -> None:
        """Неблокирующий технический вопрос об отказе (RFC-0006, шаг 2); приёмник необязателен."""
        sink = self._sink
        if sink is None or project_id is None:
            return
        incident = CapabilityIncident(
            project_id=project_id,
            capability=capability,
            status=outcome.status,
            reason=outcome.reason,
            message=outcome.message or "Возможность недоступна",
            done=outcome.done,
            remaining=outcome.remaining,
            alternatives=outcome.alternatives,
            derivation=outcome.to_json(),
        )
        try:
            await sink.report(incident)
        except Exception:
            logger.exception("Не удалось передать отказ веб-инструмента в технические вопросы")


class WebToolsSession:
    """Веб-инструменты одного прогона: пользователь, проект и общий кеш."""

    def __init__(
        self,
        tools: WebTools,
        *,
        user_id: UUID | None,
        project_id: UUID | None = None,
        cache: WebToolsCache | None = None,
    ) -> None:
        self._tools = tools
        self._user_id = user_id
        self._project_id = project_id
        self._cache = cache or WebToolsCache()

    async def search_web(
        self, query: str, *, recency_days: int | None = None, limit: int = DEFAULT_RESULTS
    ) -> WebSearchResult:
        return await self._tools.search_web(
            user_id=self._user_id,
            query=query,
            recency_days=recency_days,
            limit=limit,
            cache=self._cache,
            project_id=self._project_id,
        )

    async def read_url(self, url: str) -> WebPageResult:
        return await self._tools.read_url(
            user_id=self._user_id,
            url=url,
            cache=self._cache,
            project_id=self._project_id,
        )


__all__ = [
    "DEFAULT_RESULTS",
    "MAX_PAGE_CHARS",
    "MAX_RESULTS",
    "WebPageResult",
    "WebSearchItem",
    "WebSearchResult",
    "WebTools",
    "WebToolsCache",
    "WebToolsSession",
    "canonical_page_url",
    "checked_limit",
    "checked_page_url",
    "checked_query",
    "checked_recency",
    "provider_canonical_url",
]
