"""Извлечение текста из загруженных документов (RFC §5.2).

Mock: `.txt` и `.md` читаются по-настоящему; `.docx` — упрощённо (текст абзацев из
`word/document.xml` без таблиц и колонтитулов); `.pdf` — правдоподобный текст-заглушка.
TODO(real): #6 `.docx` → python-docx (абзацы, таблицы, нумерация), `.pdf` → pypdf с номерами
страниц для цитат; сканы без текстового слоя → статус `failed` (OCR — P2, Yandex Vision).
"""

import hashlib
import io
import zipfile
from enum import StrEnum
from typing import Protocol
from xml.etree.ElementTree import ParseError

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import fromstring

_WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_MAX_DOCX_XML_BYTES = 20 * 1024 * 1024


class DocumentFormat(StrEnum):
    TXT = "txt"
    MD = "md"
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


_PDF_PLACEHOLDERS = (
    (
        "Порядок согласования отключений потребителей при плановых ремонтах. "
        "Служба планирования формирует перечень отключаемых потребителей не позднее чем за "
        "10 дней до начала работ. Клиентская служба уведомляет потребителей. "
        "Диспетчер подтверждает время отключения в день работ."
    ),
    (
        "Положение о закупочной деятельности (выдержка). Инициатор закупки готовит "
        "техническое задание и обоснование начальной цены. Отдел закупок размещает извещение "
        "в единой информационной системе. Закупочная комиссия рассматривает заявки и "
        "подписывает протокол."
    ),
    (
        "Регламент обработки обращений потребителей. Обращение регистрируется в день "
        "поступления. Руководитель группы назначает исполнителя. Ответ готовится в течение "
        "30 дней и согласуется с юристом при наличии претензии."
    ),
)


def _pdf_placeholder(file_name: str, data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    body = _PDF_PLACEHOLDERS[digest[0] % len(_PDF_PLACEHOLDERS)]
    title = file_name.rsplit(".", 1)[0]
    return f"{title}\n\n{body}"


class MockDocumentParser:
    async def parse(self, *, file_name: str, data: bytes) -> str:
        fmt = detect_format(file_name)
        if fmt in {DocumentFormat.TXT, DocumentFormat.MD}:
            text = decode_text(data)
        elif fmt is DocumentFormat.DOCX:
            text = _docx_text(data)
        else:
            # TODO(real): #6 pypdf: текст по страницам; без текстового слоя — DocumentParseError.
            text = _pdf_placeholder(file_name, data)
        text = text.strip()
        if not text:
            raise DocumentParseError("В файле нет текста")
        return text
