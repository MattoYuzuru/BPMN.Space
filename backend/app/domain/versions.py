"""Сборка версии схемы: дифф с прошлой версией, отчёт проверки, допущения, дорожки."""

from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import datetime
from uuid import UUID

from app.domain.bpmn.diff import diff_documents
from app.domain.bpmn.document import BpmnDocument, BpmnFormatError, parse_bpmn
from app.domain.bpmn.xsd import xsd_errors
from app.domain.models import (
    AssumptionMark,
    LintIssue,
    Question,
    QuestionStatus,
    Quote,
    Report,
    Version,
    VersionOrigin,
)

_ASSUMPTION_STATUSES = {QuestionStatus.OPEN, QuestionStatus.IGNORED}


def rechecked_version(version: Version) -> Version:
    """Перепроверяет исторический флаг в ответе API, не изменяя сохранённый XML или отчёт."""
    try:
        valid = not xsd_errors(version.xml)
    except BpmnFormatError:
        valid = False
    return replace(version, report=replace(version.report, xsd_valid=valid))


def assumption_marks(questions: Iterable[Question], document: BpmnDocument) -> list[AssumptionMark]:
    """Элементы схемы, построенные на допущениях: вопрос открыт или проигнорирован."""
    present = document.all_element_ids
    return [
        AssumptionMark(element_id=element_id, question_id=q.id, text=q.assumption)
        for q in questions
        if q.status in _ASSUMPTION_STATUSES
        for element_id in q.element_ids
        if element_id in present
    ]


def build_version(
    *,
    version_id: UUID,
    project_id: UUID,
    number: int,
    origin: VersionOrigin,
    xml: str,
    previous_xml: str | None,
    questions: Iterable[Question],
    lint: list[LintIssue],
    xsd_valid: bool,
    trace: Mapping[str, Quote],
    created_at: datetime,
    run_id: UUID | None = None,
    actor_email: str | None = None,
) -> Version:
    document = parse_bpmn(xml)
    previous = parse_bpmn(previous_xml) if previous_xml is not None else None
    present = document.all_element_ids
    return Version(
        id=version_id,
        project_id=project_id,
        number=number,
        origin=origin,
        created_at=created_at,
        xml=xml,
        diff=diff_documents(previous, document),
        report=Report(
            xsd_valid=xsd_valid and not xsd_errors(xml),
            lint=lint,
            assumptions=assumption_marks(questions, document),
        ),
        trace={element_id: quote for element_id, quote in trace.items() if element_id in present},
        lanes=[lane.name for lane in document.lanes if lane.name],
        run_id=run_id,
        actor_email=actor_email,
    )
