"""Адаптеры `ocr` (RFC-0006): контракт для внешних OCR-провайдеров и их регистрация.

Основной путь OCR в волне 3 — модель с чтением PDF (Anthropic document block): страницы-сканы
читает `MediaDerivationService`, отдельный ключ не нужен. Mistral и Yandex Vision остаются
контрактами: ключ можно сохранить, «Проверить» пока отвечает `unsupported`, вызовы включит
следующая волна. В реестр они зарегистрированы через `AdapterSpec`, чтобы интерфейс настроек и
маршрутизатор знали о поддержанном провайдере заранее.
"""

from dataclasses import dataclass
from uuid import UUID

from app.domain.capabilities import Capability, CapabilityError, ErrorClass
from app.ingest.adapters.base import CapabilityAdapter
from app.ingest.adapters.vision import not_implemented

OCR_PROVIDERS: tuple[tuple[str, str], ...] = (
    ("mistral", "Mistral OCR"),
    ("yandex", "Yandex Vision OCR"),
)


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
    """`ocr_pages(source_id, pages[])` — возможность `ocr`; контракт адаптера провайдера."""

    capability = Capability.OCR
    provider = "ocr"
    model: str | None = None
    credential_id: UUID | None = None

    async def ocr_pages(self, pages: tuple[OcrPage, ...]) -> OcrResult:
        del pages
        raise not_implemented()

    async def check(self) -> str:
        raise CapabilityError(
            ErrorClass.UNSUPPORTED,
            "Ключ сохранён, но вызовы этого OCR-провайдера включит следующая волна. "
            "Страницы-сканы уже распознаёт модель с чтением PDF",
        )

    async def aclose(self) -> None:
        return None


class ContractOcrAdapter(OcrAdapter):
    """Зарегистрированный провайдер без вызовов: тип ключа и подпись для настроек."""

    def __init__(self, *, provider: str, credential_id: UUID | None = None) -> None:
        self.provider = provider
        self.credential_id = credential_id
