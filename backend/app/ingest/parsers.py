"""Извлечение текста из загруженных документов (RFC §5.2).

`.txt`/`.md` читаются напрямую, `.csv` разбирается построчно; `.docx` — упрощённо
(абзацы без таблиц и колонтитулов);
`.pdf` — через pypdf с номерами страниц (не больше `max_pdf_pages` страниц). CPU-bound разбор
идёт в отдельном потоке с ограничением по времени, чтобы не блокировать event loop.
TODO(real): OCR для PDF без текстового слоя (Yandex Vision) и полноценный `.docx` (python-docx:
таблицы, колонтитулы, списки) — сейчас берутся только абзацы.
"""

import asyncio
import csv
import io
import json
import time
import zipfile
from enum import StrEnum
from functools import partial
from typing import Protocol
from xml.etree.ElementTree import ParseError

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import fromstring
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.domain.analysis import MAX_SOURCE_TEXT_CHARS

_WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_MAX_DOCX_XML_BYTES = 20 * 1024 * 1024


class DocumentFormat(StrEnum):
    TXT = "txt"
    MD = "md"
    CSV = "csv"
    DOCX = "docx"
    PDF = "pdf"


SUPPORTED_EXTENSIONS = tuple(f".{fmt.value}" for fmt in DocumentFormat)


class UnsupportedFormatError(ValueError):
    """Формат файла не поддерживается."""


class DocumentParseError(ValueError):
    """Файл поддерживаемого формата, но текст извлечь не удалось. Сообщение — для пользователя."""


def detect_format(file_name: str) -> DocumentFormat:
    extension = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    try:
        return DocumentFormat(extension)
    except ValueError as error:
        allowed = ", ".join(SUPPORTED_EXTENSIONS)
        raise UnsupportedFormatError(f"Формат не поддерживается. Загрузите {allowed}") from error


def is_slow(fmt: DocumentFormat) -> bool:
    """Разбор, который в реальной системе идёт в фоне (источник сначала `processing`)."""
    return fmt in {DocumentFormat.DOCX, DocumentFormat.PDF}


class DocumentParser(Protocol):
    async def parse(self, *, file_name: str, data: bytes) -> str:
        """Текст документа; `UnsupportedFormatError` или `DocumentParseError` при неудаче."""
        ...


def decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise DocumentParseError("Не удалось определить кодировку текста: сохраните файл в UTF-8")


def _docx_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > _MAX_DOCX_XML_BYTES:
                raise DocumentParseError("Документ слишком большой для разбора")
            root = fromstring(archive.read(info))
    except (zipfile.BadZipFile, KeyError, ParseError, DefusedXmlException) as error:
        raise DocumentParseError("Не удалось прочитать .docx: файл повреждён") from error
    paragraphs = [
        "".join(node.text or "" for node in paragraph.iter(f"{_WORD_NS}t"))
        for paragraph in root.iter(f"{_WORD_NS}p")
    ]
    return "\n".join(paragraphs)


def _csv_text(data: bytes, *, max_chars: int) -> str:
    """Представляет ячейки CSV компактными JSON-массивами, сохраняя их порядок и значения."""
    text = decode_text(data)
    if "\x00" in text:
        raise DocumentParseError("Не удалось прочитать CSV: файл содержит бинарные данные")

    sample = text[:65_536]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel

    lines = [
        "CSV-таблица. Каждая строка ниже — JSON-массив ячеек в исходном порядке. "
        "Первая строка может содержать заголовки."
    ]
    content_chars = len(lines[0])
    has_data = False
    try:
        reader = csv.reader(io.StringIO(text, newline=""), dialect, strict=True)
        for index, row in enumerate(reader, 1):
            has_data = has_data or any(cell.strip() for cell in row)
            line = f"Строка {index}: {json.dumps(row, ensure_ascii=False)}"
            content_chars += len(line) + 1
            if content_chars > max_chars:
                raise DocumentParseError(
                    f"CSV после разбора превышает лимит {max_chars} символов. "
                    "Разделите файл на части и загрузите их отдельно"
                )
            lines.append(line)
    except csv.Error as error:
        raise DocumentParseError(
            "Не удалось прочитать CSV: проверьте кавычки и разделители"
        ) from error

    if not has_data:
        raise DocumentParseError("В CSV нет данных")
    return "\n".join(lines)


def _pdf_text(data: bytes, *, max_pages: int, max_chars: int, deadline: float) -> str:
    """Извлекает только текст PDF и сохраняет границы страниц для ссылок на цитаты.

    Работает в отдельном потоке и сам останавливается по `deadline` (монотонное время):
    поток нельзя прервать снаружи, поэтому срок проверяется между страницами.
    """
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            raise DocumentParseError("PDF защищён паролем. Снимите защиту и загрузите файл снова")
        total_pages = len(reader.pages)
        if total_pages > max_pages:
            raise DocumentParseError(
                f"В PDF {total_pages} страниц — больше лимита {max_pages}. "
                "Разделите файл на части и загрузите их отдельно"
            )
        pages: list[str] = []
        chars = 0
        for page_number, page in enumerate(reader.pages, start=1):
            if time.monotonic() > deadline:
                raise DocumentParseError(_TIMEOUT_MESSAGE)
            text = (page.extract_text() or "").strip()
            if not text:
                continue
            chars += len(text)
            if chars > max_chars:
                raise DocumentParseError(
                    f"После разбора PDF превышает лимит {max_chars} символов. "
                    "Разделите файл на части и загрузите их отдельно"
                )
            pages.append(f"[Страница {page_number}]\n{text}")
    except DocumentParseError:
        raise
    except (PdfReadError, OSError, ValueError, KeyError, TypeError) as error:
        raise DocumentParseError(
            "Не удалось прочитать PDF. Проверьте, что файл не повреждён и не защищён паролем"
        ) from error
    if not pages:
        raise DocumentParseError(
            "В PDF не найден текстовый слой. Возможно, это скан — распознайте его "
            "или вставьте текст вручную"
        )
    return "\n\n".join(pages)


_TIMEOUT_MESSAGE = (
    "Разбор файла занял слишком много времени и был остановлен. "
    "Загрузите файл поменьше или вставьте текст вручную"
)


class LocalDocumentParser:
    def __init__(
        self,
        *,
        max_text_chars: int = MAX_SOURCE_TEXT_CHARS,
        max_pdf_chars: int | None = None,
        max_pdf_pages: int = 300,
        timeout_sec: float = 60.0,
    ) -> None:
        self._max_text_chars = max_text_chars
        self._max_pdf_chars = max_pdf_chars if max_pdf_chars is not None else max_text_chars
        self._max_pdf_pages = max_pdf_pages
        self._timeout_sec = timeout_sec

    async def parse(self, *, file_name: str, data: bytes) -> str:
        fmt = detect_format(file_name)
        if fmt in {DocumentFormat.TXT, DocumentFormat.MD}:
            text = decode_text(data)
        else:
            text = await self._parse_off_loop(fmt, data)
        text = text.strip()
        if not text:
            raise DocumentParseError("В файле нет текста")
        return text

    async def _parse_off_loop(self, fmt: DocumentFormat, data: bytes) -> str:
        """CPU-bound разбор не блокирует event loop и ограничен по времени."""
        deadline = time.monotonic() + self._timeout_sec
        match fmt:
            case DocumentFormat.CSV:
                work = partial(_csv_text, data, max_chars=self._max_text_chars)
            case DocumentFormat.DOCX:
                work = partial(_docx_text, data)
            case _:
                work = partial(
                    _pdf_text,
                    data,
                    max_pages=self._max_pdf_pages,
                    max_chars=self._max_pdf_chars,
                    deadline=deadline,
                )
        try:
            return await asyncio.wait_for(asyncio.to_thread(work), timeout=self._timeout_sec)
        except TimeoutError:
            raise DocumentParseError(_TIMEOUT_MESSAGE) from None
