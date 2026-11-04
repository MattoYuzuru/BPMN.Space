"""Заготовка адаптера `vision` (RFC-0006, шаг 1): контракт без реализации вызовов.

Реализация вызовов провайдеров, кадры видео и кэш производных — отдельные волны. Адаптер
не регистрируется в реестре: ключи типа `vision` сохраняются, но пока не используются.
"""

from dataclasses import dataclass

from app.domain.capabilities import Capability, CapabilityError, ErrorClass
from app.ingest.adapters.base import CapabilityAdapter


def not_implemented() -> CapabilityError:
    """Единый отказ заготовки: понятный пользователю и помеченный классом `unsupported`."""
    return CapabilityError(
        ErrorClass.UNSUPPORTED,
        "Этот инструмент появится в следующих версиях: ключ сохранён, но пока не используется",
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class ImageRequest:
    """Изображение для `describe_images`: байты, MIME и подпись для ссылки в ответе."""

    data: bytes
    mime: str
    label: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ImageDescription:
    """Результат vision: описание и найденный на изображении текст."""

    description: str
    text: str | None = None
    provider: str = ""
    model: str | None = None
    cost_usd: float | None = None  # None — провайдер стоимость не сообщил


class VisionAdapter(CapabilityAdapter):
    """`describe_images(image_ids[], question)` — возможность `vision`."""

    capability = Capability.VISION

    async def describe_images(
        self, images: tuple[ImageRequest, ...], *, question: str
    ) -> ImageDescription:
        del images, question
        raise not_implemented()
