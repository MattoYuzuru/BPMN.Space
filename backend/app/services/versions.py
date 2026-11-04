"""Сценарии версий схемы: список, получение XML, сохранение ручной правки из bpmn-js."""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.bpmn.document import BpmnFormatError, parse_bpmn
from app.domain.bpmn.importer import retain_trace
from app.domain.bpmn.xsd import require_valid_bpmn
from app.domain.models import (
    LintIssue,
    Quote,
    RunMode,
    RunStatus,
    Version,
    VersionOrigin,
    VersionSummary,
)
from app.domain.versions import build_version
from app.infra.bpmn_tools import BpmnTools, BpmnToolsError
from app.infra.repositories.base import Repositories
from app.services.common import Runtime, get_project, get_version, too_large
from app.services.errors import (
    ConflictError,
    InvalidInputError,
    NotFoundError,
    StaleVersionError,
    UnavailableError,
)

#: Предел имени контрольной точки (совпадает с колонкой `diagram_versions.label`).
MAX_LABEL_CHARS = 120


@dataclass(frozen=True, slots=True)
class DiagramCheck:
    """Результат проверки XML без сохранения (MCP `check_diagram`, RFC-0007)."""

    xsd_valid: bool
    lint: list[LintIssue]
    lanes: list[str]
    nodes: int
    flows: int


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
    expected_base_version_id: UUID | None = None,
    enforce_base: bool = False,
    xsd_checked: bool = False,
) -> Version:
    """Новая версия: номер, дифф с прошлой, допущения по текущим вопросам, дорожки.

    Номер берётся под блокировкой проекта в одной транзакции: ручное сохранение и прогон
    (или два редактора) получают подряд идущие номера и не упираются в уникальный индекс.
    """
    if not xsd_checked:
        await asyncio.to_thread(require_valid_bpmn, xml)
    async with repos.atomic() as tx:
        if await tx.projects.lock(project_id) is None:
            raise NotFoundError("Проект не найден")
        previous = await tx.versions.latest(project_id)
        if enforce_base and (previous.id if previous else None) != expected_base_version_id:
            raise StaleVersionError(
                previous.id if previous else None, previous.number if previous else None
            )
        questions = await tx.questions.list_by_project(project_id)
        now = runtime.clock()
        version = await asyncio.to_thread(
            build_version,
            version_id=runtime.new_id(),
            project_id=project_id,
            number=previous.number + 1 if previous else 1,
            origin=origin,
            xml=xml,
            previous_xml=previous.xml if previous else None,
            questions=questions,
            lint=lint,
            xsd_valid=True,
            xsd_checked=True,
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
        session_idle_sec: float = 0.0,
        session_max_sec: float = 0.0,
    ) -> None:
        self._repos = repos
        self._tools = bpmn_tools
        self._rt = runtime
        self._max_bytes = max_diagram_bytes
        self._session_idle = session_idle_sec
        self._session_max = session_max_sec

    async def list_page(
        self, project_id: UUID, *, limit: int, before: int | None = None
    ) -> tuple[list[VersionSummary], int | None]:
        """Страница истории без XML и цитат; второй элемент — курсор `before` следующей страницы."""
        await get_project(self._repos, project_id)
        rows = await self._repos.versions.list_page(project_id, limit=limit + 1, before=before)
        page = rows[:limit]
        return page, (page[-1].number if len(rows) > limit and page else None)

    async def get(self, version_id: UUID) -> Version:
        return await get_version(self._repos, version_id)

    async def check(self, xml: str) -> DiagramCheck:
        """Проверить схему без сохранения: безопасность XML, официальная XSD и bpmnlint.

        Те же проверки, что при `save_manual`, но истории не касается: агент может посмотреть
        замечания до того, как предложить правку (RFC-0007, `check_diagram`).
        """
        if not xml.strip():
            raise InvalidInputError("Схема пустая")
        if len(xml.encode("utf-8")) > self._max_bytes:
            raise too_large("Схема", self._max_bytes)
        try:
            await asyncio.to_thread(require_valid_bpmn, xml)
            lint = await self._tools.lint(xml)
        except BpmnToolsError as error:
            raise UnavailableError(str(error)) from error
        except BpmnFormatError as error:
            raise InvalidInputError(str(error)) from error
        try:
            document = await asyncio.to_thread(parse_bpmn, xml)
        except BpmnFormatError as error:  # pragma: no cover — XSD уже отсекла повреждённый XML
            raise InvalidInputError(str(error)) from error
        return DiagramCheck(
            xsd_valid=True,
            lint=lint,
            lanes=[lane.name for lane in document.lanes],
            nodes=len(document.nodes),
            flows=len(document.flows),
        )

    async def checkpoint(
        self, project_id: UUID, version_id: UUID, *, label: str | None = None
    ) -> Version:
        """Закрепить версию как контрольную точку: она больше не принимает автосохранения."""
        name = label.strip() if label is not None else None
        if name is not None and len(name) > MAX_LABEL_CHARS:
            raise InvalidInputError(f"Название длиннее {MAX_LABEL_CHARS} символов")
        async with self._repos.atomic() as repos:
            if await repos.projects.lock(project_id) is None:
                raise NotFoundError("Проект не найден")
            current = await repos.versions.get(version_id)
            if current is None or current.project_id != project_id:
                raise NotFoundError("Версия не найдена")
            marked = await repos.versions.mark_checkpoint(version_id, name)
            if marked is None:
                raise NotFoundError("Версия не найдена")
            return marked

    def _coalescable(self, head: Version | None, actor_email: str | None, now: datetime) -> bool:
        """Автосохранение вливается в последнюю версию, пока сессия правок того же автора жива."""
        if head is None or self._session_idle <= 0 or not actor_email:
            return False
        if head.origin is not VersionOrigin.MANUAL or head.checkpoint:
            return False
        if head.actor_email != actor_email:
            return False
        last = head.updated_at or head.created_at
        started = head.session_started_at or head.created_at
        if (now - last).total_seconds() >= self._session_idle:
            return False
        return self._session_max <= 0 or (now - started).total_seconds() < self._session_max

    async def save_manual(
        self,
        project_id: UUID,
        *,
        xml: str,
        base_version_id: UUID | None = None,
        actor_email: str | None = None,
    ) -> Version:
        """Ручная правка из bpmn-js → версия `manual`.

        Проверяет безопасность XML и официальную XSD до сохранения и вызова BPMN-инструментов.
        Импорт XML → ProcessGraph для сохранения логики при сборке описан в RFC §5.3, §5.5.
        """
        await get_project(self._repos, project_id)
        if len(xml.encode("utf-8")) > self._max_bytes:
            raise too_large("Схема", self._max_bytes)
        if not xml.strip():
            raise InvalidInputError("Схема пустая")
        try:
            # Одна XSD-проверка (она же отсекает небезопасный XML: DTD, PI, script и чужие
            # пространства имён) и вне цикла событий; повторно её не вызывают ниже.
            await asyncio.to_thread(require_valid_bpmn, xml)
            lint = await self._tools.lint(xml)
        except BpmnToolsError as error:
            raise UnavailableError(str(error)) from error
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
            # Прогон в `waiting` ждёт решения пользователя и сам не движется: ручное сохранение
            # не теряется, а продолжение сборки увидит изменённую голову и попросит новый прогон.
            if (
                active is not None
                and active.mode is RunMode.BUILD
                and active.status is not RunStatus.WAITING
            ):
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
            # Повтор идентичного сохранения не раздувает историю и не меняет автора.
            if previous is not None and previous.xml == xml:
                return previous
            now = self._rt.clock()
            if (
                previous is not None
                and self._coalescable(previous, actor_email, now)
                and not await repos.versions.has_dependants(previous.id)
            ):
                return await self._coalesce(
                    repos, previous, xml=xml, lint=lint, actor_email=actor_email, now=now
                )
            trace = (
                await asyncio.to_thread(retain_trace, previous.xml, xml, previous.trace)
                if previous
                else {}
            )
            return await add_version(
                repos,
                self._rt,
                project_id=project_id,
                xml=xml,
                origin=VersionOrigin.MANUAL,
                lint=lint,
                trace=trace,
                actor_email=actor_email,
                xsd_checked=True,
            )

    async def _coalesce(
        self,
        repos: Repositories,
        head: Version,
        *,
        xml: str,
        lint: list[LintIssue],
        actor_email: str | None,
        now: datetime,
    ) -> Version:
        """Заменяет последнюю версию сессии: тот же номер, новый id, дифф от предшественника.

        Новый id нужен, чтобы `base_version_id` соавторов и вкладок честно устаревал.
        """
        base = await repos.versions.by_number(head.project_id, head.number - 1)
        questions = await repos.questions.list_by_project(head.project_id)
        trace = await asyncio.to_thread(retain_trace, base.xml, xml, base.trace) if base else {}
        version = await asyncio.to_thread(
            build_version,
            version_id=self._rt.new_id(),
            project_id=head.project_id,
            number=head.number,
            origin=VersionOrigin.MANUAL,
            xml=xml,
            previous_xml=base.xml if base else None,
            questions=questions,
            lint=lint,
            xsd_valid=True,
            xsd_checked=True,
            trace=trace,
            created_at=head.created_at,
            actor_email=actor_email,
            session_started_at=head.session_started_at,
            saved_count=head.saved_count + 1,
        )
        version.updated_at = now
        await repos.versions.replace(head.id, version)
        await repos.projects.touch(head.project_id, now)
        return version
