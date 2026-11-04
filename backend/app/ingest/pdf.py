"""Страницы PDF для OCR (RFC-0006, шаг 4): число страниц, нарезка и пометки.

Модель с чтением PDF (Anthropic document block) получает документ целиком, но у блока есть
пределы — 32 МБ и 600 страниц (и это предел закодированного запроса, а не только файла).
Крупный скан режется на части по диапазонам страниц: каждая часть — самостоятельный PDF из
исходных страниц (без перерисовки). Внутри части страницы идут подряд (1..N), и модель просят
вернуть порядковые номера — так подпись «страница 12» не зависит от того, что модель видит
двухстраничный фрагмент; обратное сопоставление делает вызывающий код.

pypdf — единственная зависимость; Pillow и poppler не нужны. Разбор PDF — CPU-bound, поэтому
сервис вызывает эти методы через `asyncio.to_thread`; `PdfSource` читает документ один раз, а
не заново на каждую часть.
"""

import io
from collections.abc import Sequence

from pypdf import PdfReader, PdfWriter

from app.domain.media import MAX_DOCUMENT_BYTES, MAX_DOCUMENT_PAGES

# Часть PDF кодируется в base64 (+33 %) и уходит в JSON-запрос: сырые байты должны быть
# заметно меньше 32 МБ, иначе провайдер ответит 413 на каждую часть.
BASE64_OVERHEAD = 4 / 3
# Предел сырых байт одной части: 22 МиБ → ≈ 29,3 МиБ base64 плюс промпт, влезает в 32 МБ.
MAX_PART_BYTES = 22 * 1024 * 1024


class PdfPagesError(ValueError):
    """PDF не прочитан или запрошенные страницы вне документа. Сообщение — для пользователя."""


class PdfSource:
    """Один раз прочитанный PDF: число страниц и нарезка частей по диапазонам."""

    def __init__(self, data: bytes) -> None:
        if not data:
            raise PdfPagesError("Пустой PDF: страницы не распознать")
        self.size = len(data)
        try:
            self._reader = PdfReader(io.BytesIO(data), strict=False)
            self.count = len(self._reader.pages)
        except Exception as error:
            raise PdfPagesError("Не удалось прочитать PDF для OCR") from error

    def take(self, pages: Sequence[int]) -> bytes:
        """PDF только из перечисленных страниц (1-based); порядок — по возрастанию номеров."""
        if not pages:
            raise PdfPagesError("Не указаны страницы для OCR")
        try:
            writer = PdfWriter()
            for page in pages:
                if not 1 <= page <= self.count:
                    raise PdfPagesError(f"Страницы {page} нет в PDF (всего {self.count})")
                writer.add_page(self._reader.pages[page - 1])
            buffer = io.BytesIO()
            writer.write(buffer)
        except PdfPagesError:
            raise
        except Exception as error:
            raise PdfPagesError("Не удалось подготовить страницы PDF для OCR") from error
        return buffer.getvalue()

    def chunks(
        self,
        pages: Sequence[int],
        *,
        max_pages: int,
        max_bytes: int = MAX_PART_BYTES,
    ) -> list[tuple[int, ...]]:
        """Части по страницам с учётом числа страниц и байтового лимита.

        Байты оцениваются пропорционально доле страниц: PDF без перерисовки не даёт точного
        размера части, но оценка не позволяет заведомо отправить слишком большой блок.
        Точный размер проверяется уже после `take`: сервис дробит часть, если она не влезла.
        """
        ordered = sorted(set(pages))
        if not ordered:
            return []
        per_page = self.size / max(self.count, 1)
        per_part = max(int(min(max_bytes, MAX_PART_BYTES) // max(per_page, 1)), 1)
        size = min(max(max_pages, 1), MAX_DOCUMENT_PAGES, per_part)
        return chunks_by_pages(ordered, size=size)


def page_count(data: bytes) -> int:
    """Число страниц; ошибка чтения — понятный `PdfPagesError`."""
    return PdfSource(data).count


def take_pages(data: bytes, pages: Sequence[int]) -> bytes:
    """PDF только из перечисленных страниц (1-based, порядок сохраняется по возрастанию)."""
    return PdfSource(data).take(pages)


def chunks_by_pages(pages: Sequence[int], *, size: int) -> list[tuple[int, ...]]:
    """Делит номера страниц на последовательные части не больше `size`."""
    step = max(int(size), 1)
    ordered = sorted(set(pages))
    return [tuple(ordered[index : index + step]) for index in range(0, len(ordered), step)]


def chunks_by_size(
    data: bytes, pages: Sequence[int], *, limit: int = MAX_PART_BYTES
) -> list[tuple[int, ...]]:
    """Части по страницам с учётом байтового лимита (см. `PdfSource.chunks`)."""
    source = PdfSource(data)
    return source.chunks(pages, max_pages=MAX_DOCUMENT_PAGES, max_bytes=limit)


__all__ = [
    "BASE64_OVERHEAD",
    "MAX_DOCUMENT_BYTES",
    "MAX_PART_BYTES",
    "PdfPagesError",
    "PdfSource",
    "chunks_by_pages",
    "chunks_by_size",
    "page_count",
    "take_pages",
]
