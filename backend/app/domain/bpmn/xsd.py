"""Проверка BPMN по официальным XSD OMG (файлы — в `xsd/` рядом).

Mock: проверяется только корректность XML и корневой элемент (`parse_bpmn`); схемы из фикстур
проходят XSD — это проверяет `tests/test_fixtures_bpmn.py` через lxml.
TODO(real): #5 `lxml.etree.XMLSchema(xsd/BPMN20.xsd)` с кэшем схемы, ошибки с номерами строк
(RFC §5.5); lxml перенести из dev-зависимостей в основные.
"""

from pathlib import Path

from app.domain.bpmn.document import parse_bpmn

XSD_DIR = Path(__file__).resolve().parent / "xsd"
XSD_ENTRY = XSD_DIR / "BPMN20.xsd"


def xsd_errors(xml: str) -> list[str]:
    """Ошибки валидации; пустой список — схема валидна. Битый XML — `BpmnFormatError`."""
    parse_bpmn(xml)
    return []
