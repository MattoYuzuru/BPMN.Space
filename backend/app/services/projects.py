"""Сценарии проектов: список с курсором и поиском, карточка, создание (в т. ч. из примера)."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.domain.access import ProjectScope
from app.domain.models import (
    Project,
    ProjectStatus,
    Question,
    Run,
    RunSummary,
    Source,
    SourceKind,
    SourceStatus,
    Version,
)
from app.domain.pagination import Cursor, InvalidCursorError
from app.domain.projects import default_source_title, derive_status
from app.domain.questions import project_summary
from app.domain.versions import rechecked_version
from app.fixtures import read_text
from app.fixtures.types import Example
from app.infra.repositories.base import ProjectStats, Repositories
from app.infra.storage import FileStorage
from app.services.common import Runtime, get_project
from app.services.errors import ConflictError, InvalidInputError, NotFoundError

logger = logging.getLogger(__name__)

MAX_PAGE = 100
MAX_TITLE = 200
MAX_DESCRIPTION = 2000


@dataclass(slots=True, kw_only=True)
class ProjectCounts:
    sources: int
    questions_open: int
    questions_resolved: int
    versions: int


@dataclass(slots=True, kw_only=True)
class ProjectView:
    project: Project
    status: ProjectStatus
    counts: ProjectCounts
    lanes: list[str]


@dataclass(slots=True, kw_only=True)
class ProjectPage:
    items: list[ProjectView]
    next_cursor: str | None
    total: int


@dataclass(slots=True, kw_only=True)
class ProjectDetail:
    view: ProjectView
    sources: list[Source]
    questions: list[Question]
    latest_version: Version | None
    active_run: Run | None
    summary: RunSummary


def _clean_title(title: str) -> str:
    title = " ".join(title.split())
    if not title:
        raise InvalidInputError("Название проекта не может быть пустым")
    if len(title) > MAX_TITLE:
        raise InvalidInputError(f"Название длиннее {MAX_TITLE} символов")
    return title


def _clean_description(description: str | None) -> str | None:
    if description is None:
        return None
    description = description.strip()
    if len(description) > MAX_DESCRIPTION:
        raise InvalidInputError(f"Описание длиннее {MAX_DESCRIPTION} символов")
    return description or None


def _build_view(project: Project, stats: ProjectStats) -> ProjectView:
    return ProjectView(
        project=project,
        status=derive_status(
            has_sources=stats.has_material,
            open_questions=stats.questions_open,
            active_run_mode=stats.active_run_mode,
        ),
        counts=ProjectCounts(
            sources=stats.sources,
            questions_open=stats.questions_open,
            questions_resolved=stats.questions_resolved,
            versions=stats.versions,
        ),
        lanes=list(stats.lanes),
    )


class ProjectService:
    def __init__(
        self,
        repos: Repositories,
        *,
        examples: Sequence[Example],
        runtime: Runtime,
        storage: FileStorage,
    ) -> None:
        self._repos = repos
        self._examples = {example.id: example for example in examples}
        self._rt = runtime
        self._storage = storage

    async def _views(self, projects: Sequence[Project]) -> list[ProjectView]:
        """Карточки пачкой: счётчики приходят агрегатами БД, а не загрузкой строк."""
        stats = await self._repos.projects.stats([p.id for p in projects]) if projects else {}
        return [_build_view(p, stats.get(p.id, ProjectStats())) for p in projects]

    async def _view(self, project: Project) -> ProjectView:
        return (await self._views([project]))[0]

    async def list(
        self,
        *,
        cursor: str | None,
        limit: int,
        query: str | None,
        owner_id: UUID | None = None,
        scope_to_user: bool = False,
        scope: ProjectScope = ProjectScope.ALL,
        only_ids: frozenset[UUID] | None = None,
    ) -> ProjectPage:
        """Курсорная страница; счётчики карточек считает БД агрегатами, без N+1.

        `only_ids` сужает выдачу до проектов токена доступа (RFC-0007); None — без сужения.
        """
        limit = min(max(limit, 1), MAX_PAGE)
        try:
            after = Cursor.decode(cursor).key() if cursor else None
        except InvalidCursorError as error:
            raise InvalidInputError(str(error)) from error
        query = query.strip() if query else None
        projects = await self._repos.projects.list_page(
            query=query,
            after=after,
            limit=limit + 1,
            owner_id=owner_id,
            scope_to_user=scope_to_user,
            scope=scope,
            only_ids=only_ids,
        )
        has_more = len(projects) > limit
        projects = projects[:limit]
        last = projects[-1] if projects else None
        return ProjectPage(
            items=await self._views(projects),
            next_cursor=Cursor(last.updated_at, last.id).encode() if has_more and last else None,
            total=await self._repos.projects.count(
                query=query,
                owner_id=owner_id,
                scope_to_user=scope_to_user,
                scope=scope,
                only_ids=only_ids,
            ),
        )

    async def get(self, project_id: UUID) -> ProjectView:
        return await self._view(await get_project(self._repos, project_id))

    async def detail(self, project_id: UUID) -> ProjectDetail:
        repos = self._repos
        project = await get_project(repos, project_id)
        sources = await repos.sources.list_by_project(project_id)
        questions = await repos.questions.list_by_project(project_id)
        latest = await repos.versions.latest(project_id)
        active = await repos.runs.active_for_project(project_id)
        last_run_id = await repos.runs.last_succeeded_id(project_id)
        view = await self._view(project)
        return ProjectDetail(
            view=view,
            sources=sources,
            questions=questions,
            latest_version=rechecked_version(latest) if latest is not None else None,
            active_run=active,
            summary=project_summary(questions, latest_run_id=last_run_id),
        )

    async def create(
        self, *, title: str, description: str | None, owner_id: UUID | None = None
    ) -> ProjectView:
        now = self._rt.clock()
        project = Project(
            id=self._rt.new_id(),
            title=_clean_title(title),
            description=_clean_description(description),
            created_at=now,
            updated_at=now,
        )
        await self._repos.projects.add(project, owner_id=owner_id)
        return _build_view(project, ProjectStats())

    async def create_from_example(
        self, example_id: str, *, owner_id: UUID | None = None
    ) -> ProjectView:
        example = self._examples.get(example_id)
        if example is None:
            raise NotFoundError("Пример не найден")
        view = await self.create(
            title=example.title, description=example.description, owner_id=owner_id
        )
        content = read_text(example.text)
        source = Source(
            id=self._rt.new_id(),
            project_id=view.project.id,
            kind=SourceKind.TEXT,
            title=default_source_title(content),
            content=content,
            status=SourceStatus.READY,
            active=True,
            created_at=view.project.created_at,
        )
        async with self._repos.atomic() as repos:
            await repos.projects.lock(view.project.id)
            await get_project(repos, view.project.id)
            await repos.sources.add(source)
        return await self._view(view.project)

    async def update(
        self, project_id: UUID, *, title: str | None, description: str | None, fields: set[str]
    ) -> ProjectView:
        """`fields` — какие поля пришли в запросе (так `description: null` очищает описание)."""
        project = await get_project(self._repos, project_id)
        if "title" in fields:
            project.title = _clean_title(title or "")
        if "description" in fields:
            project.description = _clean_description(description)
        now = self._rt.clock()
        await self._repos.projects.update(project)
        await self._repos.projects.touch(project_id, now)
        project.updated_at = max(project.updated_at, now)
        return await self._view(project)

    async def delete(self, project_id: UUID) -> None:
        """Удаляет проект одной транзакцией; файлы источников — после её фиксации."""
        async with self._repos.atomic() as repos:
            if await repos.projects.lock(project_id) is None:
                raise NotFoundError("Проект не найден")
            if await repos.runs.active_for_project(project_id):
                raise ConflictError("Нельзя удалить проект, пока идёт прогон")
            sources = await repos.sources.list_by_project(project_id)
            await repos.projects.delete(project_id)
        for source in sources:
            if source.file_key:
                try:
                    await self._storage.delete(source.file_key)
                except OSError:
                    logger.warning("Не удалён файл %s удалённого проекта", source.file_key)
