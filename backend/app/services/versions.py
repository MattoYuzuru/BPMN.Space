"""Сценарии версий схемы: список, получение XML, сохранение ручной правки из bpmn-js."""

from collections.abc import Mapping
from uuid import UUID

from app.domain.bpmn.document import BpmnFormatError, ensure_safe_xml
from app.domain.bpmn.xsd import xsd_errors
from app.domain.models import LintIssue, Quote, RunMode, Version, VersionOrigin
from app.domain.versions import build_version
from app.infra.bpmn_tools import BpmnTools
from app.infra.repositories.base import Repositories
from app.services.common import Runtime, get_project, get_version, too_large
from app.services.errors import (
    ConflictError,
    InvalidInputError,
    NotFoundError,
    StaleVersionError,
)


async def add_version(
    repos: Repositories,
    runtime: Runtime,
    *,
    project_id: UUID,
    xml: str,
    origin: VersionOrigin,
    lint: list[LintIssue],
    trace: Mapping[str, Quote],
    run_id: UUID | None = None,
    actor_email: str | None = None,
) -> Version:
    """Новая версия: номер, дифф с прошлой, допущения по текущим вопросам, дорожки.

    Номер берётся под блокировкой проекта в одной транзакции: ручное сохранение и прогон
    (или два редактора) получают подряд идущие номера и не упираются в уникальный индекс.
    """
    async with repos.atomic() as tx:
        if await tx.projects.lock(project_id) is None:
            raise NotFoundError("Проект не найден")
        previous = await tx.versions.latest(project_id)
        questions = await tx.questions.list_by_project(project_id)
        now = runtime.clock()
        version = build_version(
            version_id=runtime.new_id(),
            project_id=project_id,
            number=previous.number + 1 if previous else 1,
            origin=origin,
            xml=xml,
            previous_xml=previous.xml if previous else None,
            questions=questions,
            lint=lint,
            xsd_valid=not xsd_errors(xml),
            trace=trace,
            created_at=now,
            run_id=run_id,
            actor_email=actor_email,
        )
        await tx.versions.add(version)
        await tx.projects.touch(project_id, now)
    return version


class VersionService:
    def __init__(
        self,
        repos: Repositories,
        *,
        bpmn_tools: BpmnTools,
        runtime: Runtime,
        max_diagram_bytes: int,
    ) -> None:
        self._repos = repos
        self._tools = bpmn_tools
        self._rt = runtime
        self._max_bytes = max_diagram_bytes

    async def list(self, project_id: UUID) -> list[Version]:
        await get_project(self._repos, project_id)
        return await self._repos.versions.list_by_project(project_id)

    async def get(self, version_id: UUID) -> Version:
        return await get_version(self._repos, version_id)

    async def save_manual(
        self,
        project_id: UUID,
        *,
        xml: str,
        base_version_id: UUID | None = None,
        actor_email: str | None = None,
    ) -> Version:
        """Ручная правка из bpmn-js → версия `manual`.

        Mock: проверка корректности XML и корневого элемента BPMN, линтер — подмножество bpmnlint.
        TODO(real): #5 XSD-проверка (`domain/bpmn/xsd.py`) и импорт XML → ProcessGraph, чтобы
        следующий прогон учитывал правку логики (RFC §5.3, §5.5).
        """
        await get_project(self._repos, project_id)
        if len(xml.encode("utf-8")) > self._max_bytes:
            raise too_large("Схема", self._max_bytes)
        if not xml.strip():
            raise InvalidInputError("Схема пустая")
        try:
            xsd_errors(xml)  # mock: корректность XML и корень bpmn:definitions
            ensure_safe_xml(xml)  # только BPMN-пространства имён, без PI, DTD и script
            lint = await self._tools.lint(xml)
        except BpmnFormatError as error:
            raise InvalidInputError(str(error)) from error
        async with self._repos.atomic() as repos:
            if await repos.projects.lock(project_id) is None:
                raise NotFoundError("Проект не найден")
            # Сборка строит схему от состояния на момент старта: правка, сохранённая посреди
            # сборки, молча потерялась бы под новой версией. Анализ версий не создаёт, поэтому
            # ему правка не мешает. Блокировка проекта общая с запуском прогона, поэтому
            # проверка не обгоняется.
            active = await repos.runs.active_for_project(project_id)
            if active is not None and active.mode is RunMode.BUILD:
                raise ConflictError(
                    "Сейчас идёт сборка схемы — дождитесь её завершения и сохраните правку снова, "
                    "иначе новая версия перекроет её"
                )
            previous = await repos.versions.latest(project_id)
            current_id = previous.id if previous else None
            if current_id != base_version_id:
                raise StaleVersionError(
                    current_id, previous.number if previous is not None else None
                )
            trace = dict(previous.trace) if previous else {}
            return await add_version(
                repos,
                self._rt,
                project_id=project_id,
                xml=xml,
                origin=VersionOrigin.MANUAL,
                lint=lint,
                trace=trace,
                actor_email=actor_email,
            )
