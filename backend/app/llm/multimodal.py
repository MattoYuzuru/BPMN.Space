"""Мультимодальный вход модели (RFC-0006): изображение или PDF-документ в одном порте.

Порт `LlmClient` получает два метода — `complete_vision` (набор изображений) и
`complete_document` (один PDF). Адаптеры сами переводят вложение в формат провайдера:
Anthropic — блоки `image`/`document`, OpenAI-совместимые — `image_url` с data-URL. Промпт и
ответ остаются текстовыми, поэтому вызывающий код не зависит от провайдера.

Модуль не знает ни о ключах, ни о HTTP: только типы вложений, проверка MIME и лимиты.
Лимиты Anthropic из RFC-0006 — 32 МБ и 600 страниц на один `document`; более крупный
документ вызывающий код делит на части (см. `ingest/pdf.py`).
"""

import base64
from dataclasses import dataclass
from typing import Literal

from app.domain.media import MAX_DOCUMENT_BYTES, MAX_IMAGE_BYTES

# Пределы одного `document`-блока Anthropic (RFC-0006, «Возможности вместо провайдеров»).
__all__ = [
    "DATA_MARKER",
    "DOCUMENT_MIME_TYPES",
    "IMAGE_MIME_TYPES",
    "MAX_DOCUMENT_BYTES",
    "MAX_IMAGE_BYTES",
    "MediaAttachment",
    "MediaInputError",
    "MediaUnsupportedError",
    "document_attachment",
    "image_attachment",
    "prompt_data",
    "prompt_with_data",
]

# Метка, после которой в user-промпте идёт JSON с параметрами запроса. Единый формат для
# сервисов (они собирают `<инструкция><DATA_MARKER><json>`) и mock-а (он разбирает JSON и
# отвечает по нему). Реальная модель получает ту же структуру как обычный текст.
DATA_MARKER = "\n\nДанные:\n"

IMAGE_MIME_TYPES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})
DOCUMENT_MIME_TYPES = frozenset({"application/pdf"})

type MediaKind = Literal["image", "document"]


class MediaInputError(ValueError):
    """Вложение неверного типа или размера. Сообщение — для пользователя."""


class MediaUnsupportedError(MediaInputError):
    """Выбранная модель/провайдер не принимает такой тип вложения.

    Вызывающий код превращает это в структурированный отказ возможности и технический вопрос,
    а не в падение обработки материала.
    """


@dataclass(frozen=True, slots=True)
class MediaAttachment:
    """Локальное вложение для одного запроса: байты, MIME и необязательная подпись."""

    kind: MediaKind
    data: bytes
    mime: str
    label: str | None = None

    def __post_init__(self) -> None:
        if not self.data:
            raise MediaInputError("Вложение пустое")
        allowed = IMAGE_MIME_TYPES if self.kind == "image" else DOCUMENT_MIME_TYPES
        if self.mime not in allowed:
            raise MediaInputError(f"Тип вложения {self.mime} не поддерживается")
        limit = MAX_DOCUMENT_BYTES if self.kind == "document" else MAX_IMAGE_BYTES
        if len(self.data) > limit:
            raise MediaInputError(
                "Вложение больше допустимого размера: разделите материал на части"
            )

    @property
    def base64_data(self) -> str:
        return base64.b64encode(self.data).decode("ascii")

    def data_url(self) -> str:
        """`data:`-URL для OpenAI-совместимых `image_url`."""
        return f"data:{self.mime};base64,{self.base64_data}"


def image_attachment(
    data: bytes, *, mime: str | None = None, label: str | None = None
) -> MediaAttachment:
    """Изображение с MIME по умолчанию `image/jpeg` (кадры ffmpeg — JPEG)."""
    return MediaAttachment(kind="image", data=data, mime=mime or "image/jpeg", label=label)


def document_attachment(
    data: bytes, *, mime: str = "application/pdf", label: str | None = None
) -> MediaAttachment:
    return MediaAttachment(kind="document", data=data, mime=mime, label=label)


def prompt_with_data(instructions: str, data: str) -> str:
    """User-промпт: инструкция, затем JSON-данные после единой метки."""
    return f"{instructions.strip()}{DATA_MARKER}{data}"


def prompt_data(user: str) -> str | None:
    """JSON-часть user-промпта (для mock и для диагностики); `None` — метки нет."""
    _, marker, data = user.partition(DATA_MARKER)
    return data if marker else None
