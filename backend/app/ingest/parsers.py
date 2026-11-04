"""Извлечение текста из загруженных документов (RFC §5.2, ADR-0012).

`.txt`/`.md` читаются напрямую; `.csv` — построчно; `.docx` и `.pptx` разбираются как OOXML
(defusedxml, защита от zip-бомб): заголовки, списки и таблицы сохраняют структуру в markdown;
`.xlsx` — через openpyxl в режиме read-only, каждый лист — markdown-таблица;
`.pdf` — через pypdf с номерами страниц. Страницы PDF без текстового слоя не отбрасывают
документ: они перечисляются в `ParsedDocument.unreadable_pages`, а в текст вставляется явная
пометка, чтобы модель и аналитик видели пропуск. CPU-bound разбор идёт в отдельном потоке с
ограничением по времени, чтобы не блокировать event loop.
Колонтитулы, сноски и комментарии `.docx` не извлекаются.
TODO(real): OCR для страниц без текстового слоя (Tesseract или Yandex Vision).
"""

import asyncio
import csv
import io
import json
import re
import time
import zipfile
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime
from datetime import time as dt_time
from enum import StrEnum
from functools import partial
from typing import Any, Protocol
from xml.etree.ElementTree import Element, ParseError

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import fromstring
from openpyxl import load_workbook
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.domain.analysis import MAX_SOURCE_TEXT_CHARS

# Разбор документов идёт в собственном маленьком пуле, а не в общем пуле потоков по умолчанию
# (его делят хранилище, DeepSeek и Deepgram): зависший разбор не должен занять потоки остальных.
# По таймауту поток разбора не прерывается (Python так не умеет) — он «брошен» и доработает сам,
# занимая слот этого пула; ожидающая задача из очереди при таймауте отменяется.
_PARSE_WORKERS = 2
_parse_executor = ThreadPoolExecutor(max_workers=_PARSE_WORKERS, thread_name_prefix="doc-parse")

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
# Предел несжатого размера одной XML-части и всего архива (защита от zip-бомб).
_MAX_XML_PART_BYTES = 200 * 1024 * 1024
_MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
_MAX_ARCHIVE_MEMBERS = 20_000
_MAX_ARCHIVE_RATIO = 200
_RATIO_CHECK_FROM_BYTES = 50 * 1024 * 1024
_UNREADABLE_LIST_LIMIT = 30
_MAX_OUTLINE_LEVEL = 9
_TABLE_CELL_BREAK = " / "
_TIMEOUT_MESSAGE = (
    "Разбор файла занял слишком много времени и был остановлен. "
    "Загрузите файл поменьше или вставьте текст вручную"
)


class DocumentFormat(StrEnum):
    TXT = "txt"
    MD = "md"
    CSV = "csv"
    DOCX = "docx"
    XLSX = "xlsx"
    PPTX = "pptx"
    PDF = "pdf"


SUPPORTED_EXTENSIONS = tuple(f".{fmt.value}" for fmt in DocumentFormat)


class UnsupportedFormatError(ValueError):
    """Формат файла не поддерживается."""


class DocumentParseError(ValueError):
    """Файл поддерживаемого формата, но текст извлечь не удалось. Сообщение — для пользователя."""


class ScanOnlyPdfError(DocumentParseError):
    """PDF целиком без текстового слоя: источник `failed`, но страницы можно распознать OCR.

    Несёт номера страниц, чтобы сервис сохранил `unreadable_pages` и запустил OCR моделью:
    чистый скан — самый частый случай, и терять его только из-за отсутствия текстового слоя
    нельзя. Если модели с чтением PDF нет, это видно пользователю в техническом вопросе.
    """

    def __init__(self, message: str, *, pages: tuple[int, ...]) -> None:
        super().__init__(message)
        self.pages = pages


@dataclass(frozen=True, slots=True, kw_only=True)
class ParsedDocument:
    """Текст документа и то, что не удалось прочитать (источник остаётся `ready` с warning)."""

    text: str
    unreadable_pages: tuple[int, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def warning(self) -> str | None:
        return " ".join(self.warnings) or None


def detect_format(file_name: str) -> DocumentFormat:
    extension = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    try:
        return DocumentFormat(extension)
    except ValueError as error:
        allowed = ", ".join(SUPPORTED_EXTENSIONS)
        raise UnsupportedFormatError(f"Формат не поддерживается. Загрузите {allowed}") from error


def is_slow(fmt: DocumentFormat) -> bool:
    """Разбор, который в реальной системе идёт в фоне (источник сначала `processing`)."""
    return fmt in {
        DocumentFormat.DOCX,
        DocumentFormat.XLSX,
        DocumentFormat.PPTX,
        DocumentFormat.PDF,
    }


class DocumentParser(Protocol):
    async def parse_document(self, *, file_name: str, data: bytes) -> ParsedDocument:
        """Текст и предупреждения; `UnsupportedFormatError` или `DocumentParseError` при неудаче."""
        ...

    async def parse(self, *, file_name: str, data: bytes) -> str:
        """Только текст (удобно там, где предупреждения не нужны)."""
        ...


def decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise DocumentParseError("Не удалось определить кодировку текста: сохраните файл в UTF-8")


# --- общие помощники ---------------------------------------------------------------------


def _markdown_table(rows: list[list[str]]) -> str:
    """Строки ячеек как markdown-таблица: первая строка — заголовок (ширина — по самой длинной)."""
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    padded = [[*row, *([""] * (width - len(row)))] for row in rows]

    def line(cells: list[str]) -> str:
        return "| " + " | ".join(cells) + " |"

    separator = "| " + " | ".join(["---"] * width) + " |"
    return "\n".join([line(padded[0]), separator, *(line(row) for row in padded[1:])])


def _cell(value: str) -> str:
    """Ячейка в одну строку без `|`, чтобы не ломать таблицу."""
    return " ".join(value.replace("|", "\\|").split())


def _open_archive(data: bytes, kind: str) -> zipfile.ZipFile:
    """Открывает OOXML-архив после проверки заявленных размеров (защита от zip-бомб)."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as error:
        raise DocumentParseError(f"Не удалось прочитать {kind}: файл повреждён") from error
    infos = archive.infolist()
    total = sum(info.file_size for info in infos)
    compressed = max(sum(info.compress_size for info in infos), 1)
    if (
        len(infos) > _MAX_ARCHIVE_MEMBERS
        or total > _MAX_ARCHIVE_BYTES
        or (total > _RATIO_CHECK_FROM_BYTES and total / compressed > _MAX_ARCHIVE_RATIO)
    ):
        raise DocumentParseError("Документ слишком большой для разбора")
    return archive


def _read_xml(archive: zipfile.ZipFile, name: str, *, required: bool = True) -> Element | None:
    """XML-часть архива; чтение ограничено по фактическому размеру, а не по заголовку."""
    try:
        info = archive.getinfo(name)
    except KeyError:
        if required:
            raise DocumentParseError(
                "Не удалось прочитать файл: он повреждён или это не документ Office"
            ) from None
        return None
    if info.file_size > _MAX_XML_PART_BYTES:
        raise DocumentParseError("Документ слишком большой для разбора")
    try:
        with archive.open(info) as part:
            raw = part.read(_MAX_XML_PART_BYTES + 1)
        if len(raw) > _MAX_XML_PART_BYTES:
            raise DocumentParseError("Документ слишком большой для разбора")
        return fromstring(raw)
    except (zipfile.BadZipFile, ParseError, DefusedXmlException, OSError) as error:
        raise DocumentParseError("Не удалось прочитать файл: он повреждён") from error


def _required_xml(archive: zipfile.ZipFile, name: str) -> Element:
    root = _read_xml(archive, name)
    if root is None:  # pragma: no cover — required=True бросает исключение
        raise DocumentParseError("Не удалось прочитать файл: нет основной части")
    return root


# --- DOCX ----------------------------------------------------------------------------------


@dataclass(slots=True)
class _DocxStyles:
    heading_levels: dict[str, int]
    list_formats: dict[tuple[str, int], str]


def _heading_level(name: str) -> int | None:
    lowered = name.strip().lower()
    match = re.fullmatch(r"(?:heading|заголовок)\s*(\d)", lowered)
    if match:
        return int(match.group(1))
    return 1 if lowered in {"title", "название"} else None


def _docx_styles(archive: zipfile.ZipFile) -> _DocxStyles:
    levels: dict[str, int] = {}
    styles = _read_xml(archive, "word/styles.xml", required=False)
    if styles is not None:
        for style in styles.iter(f"{_W}style"):
            style_id = style.get(f"{_W}styleId")
            name = style.find(f"{_W}name")
            if not style_id:
                continue
            level = _heading_level(name.get(f"{_W}val", "") if name is not None else "")
            outline = style.find(f"{_W}pPr/{_W}outlineLvl")
            if level is None and outline is not None:
                value = outline.get(f"{_W}val", "")
                level = (
                    int(value) + 1 if value.isdigit() and int(value) < _MAX_OUTLINE_LEVEL else None
                )
            if level is not None:
                levels[style_id] = level
    formats: dict[tuple[str, int], str] = {}
    numbering = _read_xml(archive, "word/numbering.xml", required=False)
    if numbering is not None:
        abstract: dict[str, dict[int, str]] = {}
        for node in numbering.iter(f"{_W}abstractNum"):
            abstract_id = node.get(f"{_W}abstractNumId", "")
            for level_node in node.iter(f"{_W}lvl"):
                fmt = level_node.find(f"{_W}numFmt")
                index = level_node.get(f"{_W}ilvl", "0")
                if fmt is not None and index.isdigit():
                    abstract.setdefault(abstract_id, {})[int(index)] = fmt.get(f"{_W}val", "")
        for num in numbering.iter(f"{_W}num"):
            link = num.find(f"{_W}abstractNumId")
            num_id = num.get(f"{_W}numId", "")
            if link is not None:
                for index, fmt_name in abstract.get(link.get(f"{_W}val", ""), {}).items():
                    formats[(num_id, index)] = fmt_name
    return _DocxStyles(heading_levels=levels, list_formats=formats)


def _docx_run_text(paragraph: Element) -> str:
    parts: list[str] = []
    for node in paragraph.iter():
        if node.tag == f"{_W}t":
            parts.append(node.text or "")
        elif node.tag in {f"{_W}tab", f"{_W}br", f"{_W}cr"}:
            parts.append(" ")
    return "".join(parts)


class _DocxWalker:
    def __init__(self, styles: _DocxStyles) -> None:
        self._styles = styles
        self._counters: dict[tuple[str, int], int] = {}

    def blocks(self, container: Element) -> Iterator[str]:
        """Блоки тела документа в порядке следования: абзацы, списки, таблицы."""
        for child in container:
            if child.tag == f"{_W}p":
                block = self._paragraph(child)
                if block:
                    yield block
            elif child.tag == f"{_W}tbl":
                table = self._table(child)
                if table:
                    yield f"\n{table}\n"
            elif child.tag in {f"{_W}sdt", f"{_W}sdtContent", f"{_W}customXml"}:
                content = child.find(f"{_W}sdtContent") if child.tag == f"{_W}sdt" else child
                if content is not None:
                    yield from self.blocks(content)

    def _paragraph(self, paragraph: Element) -> str:
        text = " ".join(_docx_run_text(paragraph).split())
        if not text:
            return ""
        properties = paragraph.find(f"{_W}pPr")
        style_node = properties.find(f"{_W}pStyle") if properties is not None else None
        style_id = style_node.get(f"{_W}val", "") if style_node is not None else ""
        numbering = properties.find(f"{_W}numPr") if properties is not None else None
        level = self._styles.heading_levels.get(style_id)
        if level is not None:
            return f"{'#' * max(level, 1)} {text}"
        if numbering is not None:
            return self._list_item(numbering, text)
        return text

    def _list_item(self, numbering: Element, text: str) -> str:
        num_node = numbering.find(f"{_W}numId")
        level_node = numbering.find(f"{_W}ilvl")
        num_id = num_node.get(f"{_W}val", "") if num_node is not None else ""
        raw_level = level_node.get(f"{_W}val", "0") if level_node is not None else "0"
        level = int(raw_level) if raw_level.isdigit() else 0
        if num_id in {"", "0"}:  # numId=0 снимает нумерацию
            return text
        indent = "  " * level
        fmt = self._styles.list_formats.get((num_id, level), "bullet")
        if fmt in {"bullet", "none"}:
            return f"{indent}- {text}"
        key = (num_id, level)
        self._counters[key] = self._counters.get(key, 0) + 1
        for deeper in [k for k in self._counters if k[0] == num_id and k[1] > level]:
            del self._counters[deeper]
        return f"{indent}{self._counters[key]}. {text}"

    def _table(self, table: Element) -> str:
        rows: list[list[str]] = []
        for row in table.findall(f"{_W}tr"):
            cells: list[str] = []
            for cell in row.findall(f"{_W}tc"):
                properties = cell.find(f"{_W}tcPr")
                span_node = properties.find(f"{_W}gridSpan") if properties is not None else None
                span_value = span_node.get(f"{_W}val", "1") if span_node is not None else "1"
                span = int(span_value) if span_value.isdigit() else 1
                merge = properties.find(f"{_W}vMerge") if properties is not None else None
                continued = merge is not None and merge.get(f"{_W}val", "continue") == "continue"
                paragraphs = [
                    " ".join(text.split())
                    for p in cell.iter(f"{_W}p")
                    if (text := _docx_run_text(p)).strip()
                ]
                cells.append("" if continued else _cell(_TABLE_CELL_BREAK.join(paragraphs)))
                cells.extend([""] * (max(span, 1) - 1))
            if any(cells):
                rows.append(cells)
        return _markdown_table(rows)


def _docx_document(data: bytes) -> ParsedDocument:
    archive = _open_archive(data, ".docx")
    root = _required_xml(archive, "word/document.xml")
    body = root.find(f"{_W}body")
    if body is None:
        raise DocumentParseError("Не удалось прочитать .docx: нет текста документа")
    walker = _DocxWalker(_docx_styles(archive))
    return ParsedDocument(text="\n".join(walker.blocks(body)))


# --- PPTX ----------------------------------------------------------------------------------


def _pptx_paragraph_text(paragraph: Element) -> str:
    return " ".join("".join(t.text or "" for t in paragraph.iter(f"{_A}t")).split())


def _pptx_table(table: Element) -> str:
    rows = [
        [
            _cell(" ".join(_pptx_paragraph_text(p) for p in cell.iter(f"{_A}p")))
            for cell in row.findall(f"{_A}tc")
        ]
        for row in table.findall(f"{_A}tr")
    ]
    return _markdown_table(rows) if any(any(cells) for cells in rows) else ""


def _pptx_slide(root: Element) -> tuple[str, list[str]]:
    """Заголовок слайда и остальные блоки (абзацы, таблицы) в порядке следования."""
    title = ""
    blocks: list[str] = []
    tree = root.find(f"{_P}cSld/{_P}spTree")
    if tree is None:
        return title, blocks
    for node in tree.iter():
        if node.tag == f"{_P}sp":
            placeholder = node.find(f"{_P}nvSpPr/{_P}nvPr/{_P}ph")
            kind = placeholder.get("type", "") if placeholder is not None else ""
            lines = [
                text
                for paragraph in node.iter(f"{_A}p")
                if (text := _pptx_paragraph_text(paragraph))
            ]
            if kind in {"title", "ctrTitle"} and not title:
                title = " ".join(lines)
            elif lines and kind not in {"sldNum", "dt", "ftr"}:
                blocks.append("\n".join(f"- {line}" for line in lines))
        elif node.tag == f"{_A}tbl" and (table := _pptx_table(node)):
            blocks.append(table)
    return title, blocks


def _slide_number(name: str) -> int:
    match = re.search(r"(\d+)\.xml$", name)
    return int(match.group(1)) if match else 0


def _pptx_document(data: bytes) -> ParsedDocument:
    archive = _open_archive(data, ".pptx")
    names = sorted(
        (n for n in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
        key=_slide_number,
    )
    if not names:
        raise DocumentParseError("Не удалось прочитать .pptx: в презентации нет слайдов")
    sections: list[str] = []
    for position, name in enumerate(names, start=1):
        title, blocks = _pptx_slide(_required_xml(archive, name))
        notes_root = _read_xml(
            archive, f"ppt/notesSlides/notesSlide{_slide_number(name)}.xml", required=False
        )
        notes = (
            [t for p in notes_root.iter(f"{_A}p") if (t := _pptx_paragraph_text(p))]
            if notes_root is not None
            else []
        )
        # Номер слайда в заметках — служебное поле; оставляем только содержательный текст.
        notes = [line for line in notes if not line.isdigit()]
        parts = [f"## Слайд {position}" + (f": {title}" if title else ""), *blocks]
        if notes:
            parts.append("Заметки докладчика: " + " ".join(notes))
        if len(parts) > 1 or title:
            sections.append("\n\n".join(parts))
    return ParsedDocument(text="\n\n".join(sections))


# --- XLSX ----------------------------------------------------------------------------------


def _xlsx_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ") if value.time() != dt_time() else value.date().isoformat()
    if isinstance(value, date | dt_time):
        return value.isoformat()
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return _cell(str(value))


def _xlsx_document(data: bytes, *, max_rows: int, deadline: float) -> ParsedDocument:
    _open_archive(data, ".xlsx")  # проверка размеров до того, как openpyxl начнёт распаковку
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except (zipfile.BadZipFile, KeyError, ValueError, OSError, ParseError) as error:
        raise DocumentParseError("Не удалось прочитать .xlsx: файл повреждён") from error
    sections: list[str] = []
    warnings: list[str] = []
    try:
        for sheet in workbook.worksheets:
            rows: list[list[str]] = []
            skipped = 0
            for index, raw in enumerate(sheet.iter_rows(values_only=True), start=1):
                if index % 500 == 0 and time.monotonic() > deadline:
                    raise DocumentParseError(_TIMEOUT_MESSAGE)
                cells = [_xlsx_value(value) for value in raw]
                while cells and not cells[-1]:
                    cells.pop()
                if not cells:
                    continue
                if len(rows) >= max_rows:
                    skipped += 1
                    continue
                rows.append(cells)
            if not rows:
                continue
            sections.append(f"## Лист «{_cell(sheet.title)}»\n\n{_markdown_table(rows)}")
            if skipped:
                warnings.append(
                    f"Лист «{sheet.title}»: прочитаны первые {max_rows} строк, "
                    f"ещё {skipped} строк не включены в текст."
                )
    except (zipfile.BadZipFile, KeyError, ValueError, OSError, ParseError) as error:
        raise DocumentParseError("Не удалось прочитать .xlsx: файл повреждён") from error
    finally:
        workbook.close()
    return ParsedDocument(text="\n\n".join(sections), warnings=tuple(warnings))


# --- CSV -----------------------------------------------------------------------------------


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


# --- PDF -----------------------------------------------------------------------------------


def _unreadable_marker(page_number: int) -> str:
    return (
        f"[Страница {page_number}]\n"
        "[Текст этой страницы не извлечён: нет текстового слоя (скан или пустая страница)]"
    )


def _pdf_document(
    data: bytes, *, max_pages: int, max_chars: int, deadline: float
) -> ParsedDocument:
    """Извлекает текст PDF и сохраняет границы страниц для ссылок на цитаты.

    Работает в отдельном потоке и сам останавливается по `deadline` (монотонное время):
    поток нельзя прервать снаружи, поэтому срок проверяется между страницами.
    Страницы без текстового слоя не отбрасывают документ (ADR-0012): они помечаются в тексте
    и возвращаются в `unreadable_pages`. Если нет ни одной читаемой страницы, это ошибка
    `ScanOnlyPdfError`, но она несёт номера страниц: сервис сохраняет их и запускает OCR
    моделью с чтением PDF, чтобы чистый скан не терялся (волна 3).
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
        unreadable: list[int] = []
        for page_number, page in enumerate(reader.pages, start=1):
            if time.monotonic() > deadline:
                raise DocumentParseError(_TIMEOUT_MESSAGE)
            text = (page.extract_text() or "").strip()
            if not text:
                unreadable.append(page_number)
                pages.append(_unreadable_marker(page_number))
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
    if len(unreadable) == len(pages):
        raise ScanOnlyPdfError(
            "В PDF нет текстового слоя: это скан. Система попробует распознать страницы "
            "моделью с чтением PDF; если подходящей модели нет — добавьте ключ в настройках "
            "или вставьте текст вручную",
            pages=tuple(unreadable),
        )
    warnings: tuple[str, ...] = ()
    if unreadable:
        shown = ", ".join(map(str, unreadable[:_UNREADABLE_LIST_LIMIT]))
        more = len(unreadable) - _UNREADABLE_LIST_LIMIT
        listed = f"{shown} и ещё {more}" if more > 0 else shown
        warnings = (
            f"Нет текстового слоя на страницах: {listed} (сканы или пустые). "
            "Их содержимое в анализе не учитывается — выполните OCR и загрузите файл снова.",
        )
    return ParsedDocument(
        text="\n\n".join(pages), unreadable_pages=tuple(unreadable), warnings=warnings
    )


class LocalDocumentParser:
    def __init__(
        self,
        *,
        max_text_chars: int = MAX_SOURCE_TEXT_CHARS,
        max_pdf_chars: int | None = None,
        max_pdf_pages: int = 1000,
        max_sheet_rows: int = 20_000,
        timeout_sec: float = 180.0,
    ) -> None:
        self._max_text_chars = max_text_chars
        self._max_pdf_chars = max_pdf_chars if max_pdf_chars is not None else max_text_chars
        self._max_pdf_pages = max_pdf_pages
        self._max_sheet_rows = max_sheet_rows
        self._timeout_sec = timeout_sec

    async def parse(self, *, file_name: str, data: bytes) -> str:
        return (await self.parse_document(file_name=file_name, data=data)).text

    async def parse_document(self, *, file_name: str, data: bytes) -> ParsedDocument:
        fmt = detect_format(file_name)
        if fmt in {DocumentFormat.TXT, DocumentFormat.MD}:
            parsed = ParsedDocument(text=decode_text(data))
        else:
            parsed = await self._parse_off_loop(fmt, data)
        text = parsed.text.strip()
        if not text:
            raise DocumentParseError("В файле нет текста")
        return ParsedDocument(
            text=text, unreadable_pages=parsed.unreadable_pages, warnings=parsed.warnings
        )

    async def _parse_off_loop(self, fmt: DocumentFormat, data: bytes) -> ParsedDocument:
        """CPU-bound разбор не блокирует event loop и ограничен по времени."""
        deadline = time.monotonic() + self._timeout_sec
        match fmt:
            case DocumentFormat.CSV:
                work = partial(self._csv, data)
            case DocumentFormat.DOCX:
                work = partial(_docx_document, data)
            case DocumentFormat.PPTX:
                work = partial(_pptx_document, data)
            case DocumentFormat.XLSX:
                work = partial(
                    _xlsx_document, data, max_rows=self._max_sheet_rows, deadline=deadline
                )
            case _:
                work = partial(
                    _pdf_document,
                    data,
                    max_pages=self._max_pdf_pages,
                    max_chars=self._max_pdf_chars,
                    deadline=deadline,
                )
        try:
            future = asyncio.get_running_loop().run_in_executor(_parse_executor, work)
            return await asyncio.wait_for(future, timeout=self._timeout_sec)
        except TimeoutError:
            raise DocumentParseError(_TIMEOUT_MESSAGE) from None

    def _csv(self, data: bytes) -> ParsedDocument:
        return ParsedDocument(text=_csv_text(data, max_chars=self._max_text_chars))
