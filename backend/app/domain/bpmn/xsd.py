"""Runtime-проверка BPMN по локальным официальным XSD OMG, без внешних загрузок."""

import re
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Protocol, cast
from urllib.parse import unquote, urlsplit

from lxml import etree

from app.domain.bpmn.document import BPMN_NS, BpmnFormatError, ensure_safe_xml, parse_bpmn

XSD_DIR = Path(__file__).resolve().parent / "xsd"
XSD_ENTRY = XSD_DIR / "BPMN20.xsd"
_SCHEMA_FILES = frozenset({"BPMN20.xsd", "Semantic.xsd", "BPMNDI.xsd", "DC.xsd", "DI.xsd"})
_VALIDATION_LOCK = Lock()
_MAX_DIAGNOSTIC_ERRORS = 3
_ATTRIBUTE_NAME = re.compile(r"attribute '([^']+)'")


class _SchemaError(Protocol):
    line: int
    path: str | None
    message: str


class _Schema(Protocol):
    error_log: Iterable[_SchemaError]

    def validate(self, document: object) -> bool: ...


class _Element(Protocol):
    nsmap: dict[str | None, str]
    tag: object

    def xpath(self, expression: str, *, namespaces: dict[str, str]) -> object: ...

    def get(self, key: str) -> str | None: ...


class _Resolver(Protocol):
    def resolve_filename(self, filename: str, context: object) -> object: ...


class _LocalSchemas(etree.Resolver):
    """Компилятор схем получает только файлы из поставки, даже при изменении schemaLocation."""

    # lxml-stubs не описывает аргумент context и resolve_filename публичного C API Resolver.
    def resolve(self, url: str, _public_id: str | None, context: object) -> object:  # pyright: ignore[reportIncompatibleMethodOverride]
        parts = urlsplit(url)
        path = Path(unquote(parts.path))
        candidate = path.resolve() if path.is_absolute() else (XSD_DIR / path).resolve()
        if parts.scheme not in {"", "file"} or candidate.parent != XSD_DIR:
            raise OSError("Внешняя схема XML запрещена")
        if candidate.name not in _SCHEMA_FILES:
            raise OSError("Неизвестная схема XML запрещена")
        return cast(_Resolver, self).resolve_filename(str(candidate), context)


def _parser() -> etree.XMLParser:
    return etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)


@lru_cache(maxsize=1)
def _schema() -> _Schema:
    parser = _parser()
    parser.resolvers.add(_LocalSchemas())
    # Реальный error_log итерируем; сторонние stubs пока не описывают этот протокол.
    return cast(_Schema, etree.XMLSchema(etree.parse(str(XSD_ENTRY), parser)))


def _diagnostic(error: _SchemaError, document: _Element) -> str:
    """Номер строки и id из пути lxml; детали схемы оставляем для точной диагностики."""
    element_id: str | None = None
    element_name: str | None = None
    if error.path:
        namespaces = {key: value for key, value in document.nsmap.items() if key}
        try:
            matches = document.xpath(error.path, namespaces=namespaces)
            if isinstance(matches, list) and matches and etree.iselement(matches[0]):
                element = cast(_Element, matches[0])
                element_id = element.get("id")
                if isinstance(element.tag, str):
                    element_name = element.tag.rsplit("}", 1)[-1]
        except etree.XPathError:
            pass
    location = f"Строка {error.line}"
    if element_id:
        location += f", элемент {element_id}"
    attribute = _ATTRIBUTE_NAME.search(error.message)
    attribute_name = attribute.group(1).rsplit("}", 1)[-1] if attribute else None
    if attribute_name and "required" in error.message:
        detail = f"не указан обязательный атрибут «{attribute_name}»"
    elif attribute_name and "not allowed" in error.message:
        detail = f"атрибут «{attribute_name}» не разрешён для «{element_name or 'элемента'}»"
    elif attribute_name:
        detail = f"значение атрибута «{attribute_name}» не соответствует типу BPMN 2.0 XSD"
    else:
        detail = f"элемент «{element_name or 'BPMN'}» или порядок его содержимого нарушает XSD"
    return f"{location}: {detail}"


def xsd_errors(xml: str) -> list[str]:
    """Пустой список означает выполненную XSD-проверку. Небезопасный XML — BpmnFormatError."""
    parse_bpmn(xml)
    ensure_safe_xml(xml)
    try:
        document = etree.fromstring(xml.encode("utf-8"), _parser())
    except etree.XMLSyntaxError as error:
        raise BpmnFormatError(f"XML повреждён: строка {error.lineno}") from error
    if document.find(f"{{{BPMN_NS}}}import") is not None:
        raise BpmnFormatError("Внешние импорты BPMN запрещены: схема должна быть самодостаточной")
    # error_log принадлежит экземпляру схемы: проверка и чтение ошибок должны быть атомарны.
    with _VALIDATION_LOCK:
        schema = _schema()
        if schema.validate(document):
            return []
        return [_diagnostic(error, cast(_Element, document)) for error in schema.error_log]


def require_valid_bpmn(xml: str) -> None:
    """Общий гейт перед созданием версии, включая XML после автоматической раскладки."""
    errors = xsd_errors(xml)
    if errors:
        detail = "; ".join(errors[:_MAX_DIAGNOSTIC_ERRORS])
        if len(errors) > _MAX_DIAGNOSTIC_ERRORS:
            detail += f"; ещё ошибок: {len(errors) - _MAX_DIAGNOSTIC_ERRORS}"
        raise BpmnFormatError(f"Схема не прошла проверку BPMN 2.0 XSD: {detail}")
