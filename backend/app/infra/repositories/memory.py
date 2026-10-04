"""In-memory реализация репозиториев (mock, #2).

Хранит копии сущностей: изменение объекта без `update()` не попадает в хранилище — так же,
как будет с БД. Данные живут до рестарта процесса.
TODO(real): #6 заменить на `infra/db/` (SQLAlchemy + Postgres), см. `base.py`.
"""

import copy
from collections.abc import Iterable
from dataclasses import dataclass, field
from uuid import UUID

from app.domain.access import ProjectScope
from app.domain.models import LlmCall, Project, Question, QuestionStatus, Run, Source, Version
from app.domain.questions import normalize
from app.domain.runs import ACTIVE_STATUSES
from app.infra.repositories.base import PageKey, Repositories


@dataclass(slots=True)
class InMemoryStore:
    projects: dict[UUID, Project] = field(default_factory=dict[UUID, Project])
    sources: dict[UUID, Source] = field(default_factory=dict[UUID, Source])
    questions: dict[UUID, Question] = field(default_factory=dict[UUID, Question])
    runs: dict[UUID, Run] = field(default_factory=dict[UUID, Run])
    versions: dict[UUID, Version] = field(default_factory=dict[UUID, Version])
    llm_calls: dict[UUID, LlmCall] = field(default_factory=dict[UUID, LlmCall])
    project_owners: dict[UUID, UUID] = field(default_factory=dict[UUID, UUID])
    public_projects: set[UUID] = field(default_factory=set[UUID])

    def load(
        self,
        *,
        projects: Iterable[Project] = (),
        sources: Iterable[Source] = (),
        questions: Iterable[Question] = (),
        runs: Iterable[Run] = (),
        versions: Iterable[Version] = (),
    ) -> None:
        """Синхронная загрузка сида при старте приложения."""
        self.projects.update({p.id: copy.deepcopy(p) for p in projects})
        self.public_projects.update(p.id for p in projects)
        self.sources.update({s.id: copy.deepcopy(s) for s in sources})
        self.questions.update({q.id: copy.deepcopy(q) for q in questions})
        self.runs.update({r.id: copy.deepcopy(r) for r in runs})
        self.versions.update({v.id: copy.deepcopy(v) for v in versions})

    def repositories(self) -> Repositories:
        return Repositories(
            projects=InMemoryProjectRepository(self),
            sources=InMemorySourceRepository(self),
            questions=InMemoryQuestionRepository(self),
            runs=InMemoryRunRepository(self),
            versions=InMemoryVersionRepository(self),
            llm_calls=InMemoryLlmCallRepository(self),
        )


def _sort_key(project: Project) -> PageKey:
    return (project.updated_at, project.id)


class InMemoryProjectRepository:
    def __init__(self, store: InMemoryStore) -> None:
        self._store = store
        self._items = store.projects

    async def add(
        self, project: Project, *, owner_id: UUID | None = None, public: bool = False
    ) -> None:
        self._items[project.id] = copy.deepcopy(project)
        if public:
            self._store.public_projects.add(project.id)
        if owner_id is not None:
            self._store.project_owners[project.id] = owner_id

    async def get(self, project_id: UUID) -> Project | None:
        item = self._items.get(project_id)
        return copy.deepcopy(item) if item else None

    async def update(self, project: Project) -> None:
        self._items[project.id] = copy.deepcopy(project)

    async def delete(self, project_id: UUID) -> None:
        self._items.pop(project_id, None)
        self._store.project_owners.pop(project_id, None)
        self._store.public_projects.discard(project_id)

    def _matching(self, query: str | None) -> list[Project]:
        needle = normalize(query or "")
        return [p for p in self._items.values() if needle in normalize(p.title)]

    def _visible(
        self, items: list[Project], owner_id: UUID | None, scope: ProjectScope
    ) -> list[Project]:
        """Видимость в памяти: демо и свои проекты; редакторов без аккаунтов (PostgreSQL) нет."""
        public = self._store.public_projects
        own = [p for p in items if owner_id and self._store.project_owners.get(p.id) == owner_id]
        match scope:
            case ProjectScope.OWN:
                return own
            case ProjectScope.SHARED:
                return []
            case ProjectScope.EXAMPLES:
                return [p for p in items if p.id in public]
            case _:
                return [p for p in items if p.id in public or p in own]

    async def list_page(
        self,
        *,
        query: str | None,
        after: PageKey | None,
        limit: int,
        owner_id: UUID | None = None,
        scope_to_user: bool = False,
        scope: ProjectScope = ProjectScope.ALL,
    ) -> list[Project]:
        items = sorted(self._matching(query), key=_sort_key, reverse=True)
        if scope_to_user:
            items = self._visible(items, owner_id, scope)
        if after is not None:
            items = [p for p in items if _sort_key(p) < after]
        return [copy.deepcopy(p) for p in items[:limit]]

    async def count(
        self,
        *,
        query: str | None,
        owner_id: UUID | None = None,
        scope_to_user: bool = False,
        scope: ProjectScope = ProjectScope.ALL,
    ) -> int:
        items = self._matching(query)
        if scope_to_user:
            items = self._visible(items, owner_id, scope)
        return len(items)


class InMemorySourceRepository:
    def __init__(self, store: InMemoryStore) -> None:
        self._items = store.sources

    async def add(self, source: Source) -> None:
        self._items[source.id] = copy.deepcopy(source)

    async def get(self, source_id: UUID) -> Source | None:
        item = self._items.get(source_id)
        return copy.deepcopy(item) if item else None

    async def update(self, source: Source) -> None:
        self._items[source.id] = copy.deepcopy(source)

    async def delete(self, source_id: UUID) -> None:
        self._items.pop(source_id, None)

    async def list_by_project(self, project_id: UUID) -> list[Source]:
        items = [s for s in self._items.values() if s.project_id == project_id]
        return [copy.deepcopy(s) for s in sorted(items, key=lambda s: (s.created_at, s.id))]

    async def delete_by_project(self, project_id: UUID) -> None:
        for key in [k for k, s in self._items.items() if s.project_id == project_id]:
            del self._items[key]


def _code_number(question: Question) -> int:
    digits = question.code.removeprefix("Q-")
    return int(digits) if digits.isdigit() else 0


class InMemoryQuestionRepository:
    def __init__(self, store: InMemoryStore) -> None:
        self._items = store.questions

    async def add(self, question: Question) -> None:
        self._items[question.id] = copy.deepcopy(question)

    async def get(self, question_id: UUID) -> Question | None:
        item = self._items.get(question_id)
        return copy.deepcopy(item) if item else None

    async def update(self, question: Question) -> None:
        self._items[question.id] = copy.deepcopy(question)

    async def list_by_project(
        self, project_id: UUID, *, status: QuestionStatus | None = None
    ) -> list[Question]:
        items = [
            q
            for q in self._items.values()
            if q.project_id == project_id and (status is None or q.status is status)
        ]
        return [copy.deepcopy(q) for q in sorted(items, key=_code_number)]

    async def delete_by_project(self, project_id: UUID) -> None:
        for key in [k for k, q in self._items.items() if q.project_id == project_id]:
            del self._items[key]


class InMemoryRunRepository:
    def __init__(self, store: InMemoryStore) -> None:
        self._items = store.runs

    async def add(self, run: Run) -> None:
        self._items[run.id] = copy.deepcopy(run)

    async def get(self, run_id: UUID) -> Run | None:
        item = self._items.get(run_id)
        return copy.deepcopy(item) if item else None

    async def update(self, run: Run) -> None:
        self._items[run.id] = copy.deepcopy(run)

    async def list_by_project(self, project_id: UUID) -> list[Run]:
        items = [r for r in self._items.values() if r.project_id == project_id]
        return [copy.deepcopy(r) for r in sorted(items, key=lambda r: (r.started_at, r.id))]

    async def active_for_project(self, project_id: UUID) -> Run | None:
        for run in self._items.values():
            if run.project_id == project_id and run.status in ACTIVE_STATUSES:
                return copy.deepcopy(run)
        return None

    async def delete_by_project(self, project_id: UUID) -> None:
        for key in [k for k, r in self._items.items() if r.project_id == project_id]:
            del self._items[key]


class InMemoryVersionRepository:
    def __init__(self, store: InMemoryStore) -> None:
        self._items = store.versions

    async def add(self, version: Version) -> None:
        self._items[version.id] = copy.deepcopy(version)

    async def get(self, version_id: UUID) -> Version | None:
        item = self._items.get(version_id)
        return copy.deepcopy(item) if item else None

    async def list_by_project(self, project_id: UUID) -> list[Version]:
        items = [v for v in self._items.values() if v.project_id == project_id]
        return [copy.deepcopy(v) for v in sorted(items, key=lambda v: v.number, reverse=True)]

    async def latest(self, project_id: UUID) -> Version | None:
        items = await self.list_by_project(project_id)
        return items[0] if items else None

    async def delete_by_project(self, project_id: UUID) -> None:
        for key in [k for k, v in self._items.items() if v.project_id == project_id]:
            del self._items[key]


class InMemoryLlmCallRepository:
    def __init__(self, store: InMemoryStore) -> None:
        self._items = store.llm_calls

    async def add(self, call: LlmCall) -> None:
        self._items[call.id] = copy.deepcopy(call)
