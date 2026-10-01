"""Клиент сервиса bpmn-tools: раскладка (DI) и линтер схем (RFC §4, §6).

Mock: раскладку не делает (фикстуры и линейный mock-компилятор уже содержат координаты),
линтер — подмножество правил bpmnlint на Python (`app/domain/bpmn/lint.py`).
TODO(real): #6 HTTP-клиент к Node-сервису bpmn-tools: `POST /layout` (bpmn-auto-layout
2.0.0-alpha.2, версия закреплена) и `POST /lint` (bpmnlint:recommended); таймауты и запасной
раскладчик «ранг × полоса дорожки» при ошибке alpha-версии (RFC §11). URL — в config.py.
"""

from typing import Protocol

from app.domain.bpmn.document import parse_bpmn
from app.domain.bpmn.lint import lint_document
from app.domain.models import LintIssue


class BpmnTools(Protocol):
    async def layout(self, xml: str) -> str:
        """Возвращает тот же процесс с координатами (BPMN DI)."""
        ...

    async def lint(self, xml: str) -> list[LintIssue]: ...


class MockBpmnTools:
    async def layout(self, xml: str) -> str:
        document = parse_bpmn(xml)
        if not document.has_layout:
            # TODO(real): #6 вызвать bpmn-tools /layout; mock-схемы всегда приходят с DI.
            raise ValueError("Mock bpmn-tools не умеет раскладывать схемы без координат")
        return xml

    async def lint(self, xml: str) -> list[LintIssue]:
        return lint_document(parse_bpmn(xml))
