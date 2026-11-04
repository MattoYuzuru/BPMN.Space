"""Схемы версий BPMN-схемы."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.api.schemas.common import ApiModel, ErrorResponse, Quote
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


class VersionSummary(ApiModel):
    """Строка истории: без XML, цитат и полного отчёта проверки."""

    id: UUID
    project_id: UUID
    number: int
    origin: VersionOrigin
    created_at: datetime = Field(description="Начало сессии правок (для сборки — момент сборки)")
    run_id: UUID | None = None
    actor_email: str | None = Field(
        default=None, description="Автор версии; null для старых записей"
    )
    diff: VersionDiff = Field(description="Сравнение с предыдущей версией")
    lint_count: int = Field(description="Замечаний bpmnlint")
    assumption_count: int = Field(description="Элементов на допущениях")
    label: str | None = Field(default=None, description="Имя контрольной точки")
    checkpoint: bool = Field(description="Версия закреплена и не принимает автосохранения")
    session_started_at: datetime = Field(description="Начало сессии правок")
    updated_at: datetime = Field(description="Последнее автосохранение, влитое в версию")
    saved_count: int = Field(description="Сколько автосохранений влито в версию")


class VersionPage(ApiModel):
    items: list[VersionSummary] = Field(description="Версии по убыванию номера")
    next_before: int | None = Field(
        default=None, description="Значение `before` для следующей страницы; null — конец истории"
    )


class Version(VersionSummary):
    report: VersionReport
    trace: dict[str, Quote] = Field(description="Трассировка: id элемента схемы → цитата")
    lanes: list[str] = Field(description="Названия дорожек")


class VersionDetail(Version):
    xml: str = Field(description="BPMN 2.0 XML с координатами (DI)")


class DiagramSave(ApiModel):
    xml: str = Field(min_length=1, description="BPMN 2.0 XML из bpmn-js (`saveXML`)")
    base_version_id: UUID | None = Field(
        description="Версия, от которой сделана правка; null только до первой версии"
    )


class DiagramConflictResponse(ErrorResponse):
    code: Literal["stale_version"] | None = Field(
        default=None, description="Причина конфликта, если сохранение основано на старой версии"
    )
    head_version_id: UUID | None = Field(
        default=None, description="Текущая версия проекта для синхронизации"
    )
    head_version_number: int | None = Field(
        default=None, description="Номер текущей версии проекта"
    )


class CheckpointRequest(ApiModel):
    label: str | None = Field(
        default=None, max_length=120, description="Имя контрольной точки; пустое — без имени"
    )
