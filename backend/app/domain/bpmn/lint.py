"""Минимальная проверка структуры схемы — подмножество правил `bpmnlint:recommended`.

Нужна mock-реализации `BpmnTools.lint`, сиду и проверке ручной правки, чтобы отчёт был честным
для любой схемы. Имена правил совпадают с bpmnlint, сообщения — на русском.
TODO(real): #6 полный набор правил — сервис bpmn-tools `/lint` (bpmnlint), RFC §4, §5.5.
"""

from app.domain.bpmn.document import BpmnDocument, BpmnNode
from app.domain.models import LintIssue, LintSeverity

_ACTIVITY_SUFFIXES = ("Task", "task", "subProcess", "callActivity")


def _is_activity(node: BpmnNode) -> bool:
    return node.type.endswith(_ACTIVITY_SUFFIXES)


def _is_event(node: BpmnNode) -> bool:
    return node.type.endswith("Event")


def _needs_label(node: BpmnNode) -> bool:
    if node.type in {"parallelGateway", "eventBasedGateway"}:
        return False
    if node.type.endswith("Gateway"):
        return node.outgoing > 1
    return True


def lint_document(document: BpmnDocument) -> list[LintIssue]:
    issues: list[LintIssue] = []
    starts = [n for n in document.nodes.values() if n.type == "startEvent"]
    ends = [n for n in document.nodes.values() if n.type == "endEvent"]
    if not starts:
        issues.append(_issue("start-event-required", "В процессе нет стартового события"))
    if not ends:
        issues.append(_issue("end-event-required", "В процессе нет завершающего события"))

    for node in document.nodes.values():
        if _needs_label(node) and not node.name:
            issues.append(_issue("label-required", "У элемента нет подписи", node.id))
        if node.type not in {"startEvent", "boundaryEvent"} and node.incoming == 0:
            issues.append(
                _issue("no-implicit-start", "Нет входящего потока: элемент недостижим", node.id)
            )
        if node.type != "endEvent" and node.outgoing == 0:
            issues.append(
                _issue("no-implicit-end", "Нет исходящего потока: процесс обрывается", node.id)
            )
        if (_is_activity(node) or _is_event(node)) and node.incoming > 1:
            issues.append(
                _issue(
                    "fake-join",
                    "Входящие потоки не объединены шлюзом",
                    node.id,
                    severity=LintSeverity.WARNING,
                )
            )
    return issues


def _issue(
    rule: str,
    message: str,
    element_id: str | None = None,
    *,
    severity: LintSeverity = LintSeverity.ERROR,
) -> LintIssue:
    return LintIssue(rule=rule, message=message, element_id=element_id, severity=severity)
