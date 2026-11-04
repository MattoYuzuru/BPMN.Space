"""Заготовки адаптеров `web_search` и `web_fetch` (RFC-0006, шаг 1): только контракт.

Результаты поиска и публичных страниц станут источниками `origin=derived`, `trust=external`
с URL и датой получения. Закрытые системы (Confluence, порталы за логином) так не читаются:
их закрывают внешние агенты пользователя через MCP (RFC-0007).
"""

from dataclasses import dataclass
from datetime import datetime

from app.domain.capabilities import Capability
from app.ingest.adapters.base import CapabilityAdapter
from app.ingest.adapters.vision import not_implemented


@dataclass(frozen=True, slots=True, kw_only=True)
class WebSearchRequest:
    """Поисковый запрос: формулировка и необязательная свежесть."""

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


class WebSearchAdapter(CapabilityAdapter):
    """`search_web(query, recency?)` — возможность `web_search`."""

    capability = Capability.WEB_SEARCH

    async def search(self, request: WebSearchRequest) -> tuple[WebSearchHit, ...]:
        del request
        raise not_implemented()


@dataclass(frozen=True, slots=True, kw_only=True)
class WebPage:
    """Прочитанная страница: текст, ссылка и дата получения (для провенанса)."""

    url: str
    text: str
    fetched_at: datetime
    title: str | None = None


class WebFetchAdapter(CapabilityAdapter):
    """`read_url(url)` — возможность `web_fetch`."""

    capability = Capability.WEB_FETCH

    async def fetch(self, url: str) -> WebPage:
        del url
        raise not_implemented()
