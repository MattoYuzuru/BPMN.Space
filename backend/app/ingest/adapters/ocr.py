"""Заготовка адаптера `ocr` (RFC-0006, шаг 1): контракт без реализации вызовов.

Сканы страниц PDF обрабатываются в волне OCR; пока страницы без текстового слоя остаются в
`unreadable_pages` источника с предупреждением (ADR-0012).
"""

from dataclasses import dataclass

from app.domain.capabilities import Capability
from app.ingest.adapters.base import CapabilityAdapter
from app.ingest.adapters.vision import not_implemented


@dataclass(frozen=True, slots=True, kw_only=True)
class OcrPage:
    """Страница для OCR: номер и изображение страницы."""

    page: int
    data: bytes
    mime: str = "image/png"


@dataclass(frozen=True, slots=True, kw_only=True)
class OcrResult:
    """Текст страниц с разметкой; `pages` — по номеру страницы."""

    pages: dict[int, str]
    provider: str = ""
    model: str | None = None
    cost_usd: float | None = None


class OcrAdapter(CapabilityAdapter):
    """`ocr_pages(source_id, pages[])` — возможность `ocr`."""

    capability = Capability.OCR

    async def ocr_pages(self, pages: tuple[OcrPage, ...]) -> OcrResult:
        del pages
        raise not_implemented()
