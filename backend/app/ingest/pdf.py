"""Страницы PDF для OCR (RFC-0006, шаг 4): число страниц, нарезка и пометки.

Модель с чтением PDF (Anthropic document block) получает документ целиком, но у блока есть
пределы — 32 МБ и 600 страниц. Крупный скан режется на части по диапазонам страниц: каждая
часть — самостоятельный PDF из исходных страниц (без перерисовки), поэтому номера страниц в
ответе модели остаются исходными. pypdf — единственная зависимость; Pillow и poppler не нужны.
"""

import io
from collections.abc import Sequence

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError

from app.domain.media import MAX_DOCUMENT_BYTES


class PdfPagesError(ValueError):
    """PDF не прочитан или запрошенные страницы вне документа. Сообщение — для пользователя."""


def page_count(data: bytes) -> int:
    """Число страниц; ошибка чтения — понятный `PdfPagesError`."""
    try:
        return len(PdfReader(io.BytesIO(data), strict=False).pages)
    except (PdfReadError, OSError, ValueError, KeyError, TypeError) as error:
        raise PdfPagesError("Не удалось прочитать PDF для OCR") from error


def take_pages(data: bytes, pages: Sequence[int]) -> bytes:
    """PDF только из перечисленных страниц (1-based, порядок сохраняется по возрастанию)."""
    if not pages:
        raise PdfPagesError("Не указаны страницы для OCR")
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        total = len(reader.pages)
        writer = PdfWriter()
        for page in pages:
            if not 1 <= page <= total:
                raise PdfPagesError(f"Страницы {page} нет в PDF (всего {total})")
            writer.add_page(reader.pages[page - 1])
        buffer = io.BytesIO()
        writer.write(buffer)
    except PdfPagesError:
        raise
    except (PdfReadError, OSError, ValueError, KeyError, TypeError) as error:
        raise PdfPagesError("Не удалось подготовить страницы PDF для OCR") from error
    return buffer.getvalue()


def chunks_by_pages(pages: Sequence[int], *, size: int) -> list[tuple[int, ...]]:
    """Делит номера страниц на последовательные части не больше `size`."""
    step = max(int(size), 1)
    ordered = sorted(set(pages))
    return [tuple(ordered[index : index + step]) for index in range(0, len(ordered), step)]


def chunks_by_size(
    data: bytes, pages: Sequence[int], *, limit: int = MAX_DOCUMENT_BYTES
) -> list[tuple[int, ...]]:
    """Части по страницам с учётом байтового лимита: крупные сканы 32 МБ не проходят целиком.

    Байты части оцениваются пропорционально доле страниц в документе: PDF без перерисовки
    страниц не даёт точного размера части, но грубая оценка не даёт отправить заведомо
    слишком большой блок. Если даже одна страница не проходит лимит, она всё равно уходит
    отдельной частью — провайдер ответит отказом `unsupported`, и это видно как технический
    вопрос, а не тихая потеря.
    """
    ordered = sorted(set(pages))
    total = page_count(data)
    per_page = len(data) / max(total, 1)
    per_part = max(int(limit // per_page), 1) if per_page > 0 else len(ordered)
    return chunks_by_pages(ordered, size=per_part)
