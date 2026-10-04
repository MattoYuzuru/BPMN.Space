"""Схемы версий BPMN-схемы."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.api.schemas.common import ApiModel, Quote
from app.domain.models import LintSeverity, VersionOrigin


class VersionDiff(ApiModel):
    """Сравнение с предыдущей версией по узлам и дорожкам."""

    added: int
    removed: int
    changed: int


class LintIssue(ApiModel):
    rule: str = Field(description="Правило bpmnlint, например `label-required`")
    message: str
    element_id: str | None = None
    severity: LintSeverity


class Assumption(ApiModel):
    """Элемент схемы, построенный на допущении неотвеченного вопроса."""

    element_id: str
    question_id: UUID
    text: str


class VersionReport(ApiModel):
    xsd_valid: bool
    lint: list[LintIssue]
    assumptions: list[Assumption]


class Version(ApiModel):
    id: UUID
    project_id: UUID
    number: int
    origin: VersionOrigin
    created_at: datetime
    run_id: UUID | None = None
    actor_email: str | None = Field(
        default=None, description="Автор версии; null для старых записей"
    )
    diff: VersionDiff
    report: VersionReport
    trace: dict[str, Quote] = Field(description="Трассировка: id элемента схемы → цитата")
    lanes: list[str] = Field(description="Названия дорожек")


class VersionDetail(Version):
    xml: str = Field(description="BPMN 2.0 XML с координатами (DI)")


class DiagramSave(ApiModel):
    xml: str = Field(min_length=1, description="BPMN 2.0 XML из bpmn-js (`saveXML`)")
