"""In-memory реализация репозиториев (mock, #2).

Хранит копии сущностей: изменение объекта без `update()` не попадает в хранилище — так же,
как будет с БД. Данные живут до рестарта процесса.
Нужен для тестов сервисов и локального режима без БД; в приложении с `DATABASE_URL` работает
SQL-реализация (`sql.py`). Операции здесь не прерываются между `await`, поэтому атомарны сами:
`Repositories.atomic()` — пустой контекст, `lock()` ничего не блокирует.
"""

import copy
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from app.domain.access import ProjectScope
from app.domain.models import (
    LlmCall,
    Project,
    Question,
    QuestionStatus,
    Run,
    Source,
    SourceStatus,
    Version,
)
from app.domain.onboarding import (
    ChecklistItem,
    CompletedItem,
    ItemSource,
    TourStatus,
    TourStepKey,
    UserOnboarding,
)
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
    onboarding: dict[UUID, UserOnboarding] = field(default_factory=dict[UUID, UserOnboarding])
    onboarding_items: dict[tuple[UUID, ChecklistItem], CompletedItem] = field(
        default_factory=dict[tuple[UUID, ChecklistItem], CompletedItem]
    )

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
            onboarding=InMemoryOnboardingRepository(self),
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
        stored = self._items.get(project.id)
        if stored is not None:
            stored.title = project.title
            stored.description = project.description

    async def touch(self, project_id: UUID, at: datetime) -> None:
        stored = self._items.get(project_id)
        if stored is not None and at > stored.updated_at:
            stored.updated_at = at

    async def owner_of(self, project_id: UUID) -> UUID | None:
        return self._store.project_owners.get(project_id)

    async def lock(self, project_id: UUID) -> Project | None:
        return await self.get(project_id)

    async def delete(self, project_id: UUID) -> None:
        store = self._store
        if self._items.pop(project_id, None) is None:
            return
        for items in (store.sources, store.questions, store.runs, store.versions):
            for key in [k for k, item in items.items() if item.project_id == project_id]:
                del items[key]
        for key in [k for k, call in store.llm_calls.items() if call.run_id not in store.runs]:
            del store.llm_calls[key]
        self._store.project_owners.pop(project_id, None)
        self._store.public_projects.discard(project_id)
        for state in store.onboarding.values():
            if state.tour_project_id == project_id:
                state.tour_project_id = None  # как ON DELETE SET NULL в PostgreSQL

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

    async def patch(
        self,
        source_id: UUID,
        changes: Mapping[str, Any],
        *,
        only_status: SourceStatus | None = None,
    ) -> bool:
        unknown = set(changes) - {"title", "content", "status", "active", "error"}
        if unknown:
            raise ValueError(f"Поля источника нельзя менять точечно: {sorted(unknown)}")
        stored = self._items.get(source_id)
        if stored is None or (only_status is not None and stored.status is not only_status):
            return False
        for name, value in changes.items():
            setattr(stored, name, value)
        return True

    async def fail_processing(self, error: str) -> int:
        stuck = [s for s in self._items.values() if s.status is SourceStatus.PROCESSING]
        for source in stuck:
            source.status = SourceStatus.FAILED
            source.error = error
        return len(stuck)

    async def delete(self, source_id: UUID) -> None:
        self._items.pop(source_id, None)

    async def list_by_project(self, project_id: UUID) -> list[Source]:
        items = [s for s in self._items.values() if s.project_id == project_id]
        return [copy.deepcopy(s) for s in sorted(items, key=lambda s: (s.created_at, s.id))]


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

    async def apply_reconciled(
        self, question: Question, *, expected_status: QuestionStatus
    ) -> bool:
        current = self._items.get(question.id)
        if current is None or current.status is not expected_status:
            return False
        current.status = question.status
        current.evidence = copy.deepcopy(question.evidence)
        current.answer = copy.deepcopy(question.answer)
        current.updated_at = question.updated_at
        return True

    async def list_by_project(
        self, project_id: UUID, *, status: QuestionStatus | None = None
    ) -> list[Question]:
        items = [
            q
            for q in self._items.values()
            if q.project_id == project_id and (status is None or q.status is status)
        ]
        return [copy.deepcopy(q) for q in sorted(items, key=_code_number)]


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


class InMemoryLlmCallRepository:
    def __init__(self, store: InMemoryStore) -> None:
        self._items = store.llm_calls

    async def add(self, call: LlmCall) -> None:
        self._items[call.id] = copy.deepcopy(call)


class InMemoryOnboardingRepository:
    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    async def get_or_create(self, user_id: UUID, now: datetime) -> UserOnboarding:
        state = self._store.onboarding.get(user_id)
        if state is None:
            state = UserOnboarding(
                user_id=user_id,
                tour_status=TourStatus.PENDING,
                tour_step=None,
                tour_project_id=None,
                checklist_hidden=False,
                created_at=now,
                updated_at=now,
            )
            self._store.onboarding[user_id] = state
        return copy.deepcopy(state)

    async def save_tour(
        self,
        user_id: UUID,
        *,
        expected_status: TourStatus,
        status: TourStatus,
        step: TourStepKey | None,
        project_id: UUID | None,
        now: datetime,
    ) -> bool:
        state = self._store.onboarding.get(user_id)
        if state is None or state.tour_status is not expected_status:
            return False
        state.tour_status = status
        state.tour_step = step
        state.tour_project_id = project_id
        state.updated_at = now
        return True

    async def set_checklist_hidden(self, user_id: UUID, hidden: bool, now: datetime) -> None:
        state = self._store.onboarding.get(user_id)
        if state is not None:
            state.checklist_hidden = hidden
            state.updated_at = now

    async def list_items(self, user_id: UUID) -> list[CompletedItem]:
        items = [
            item for (owner, _), item in self._store.onboarding_items.items() if owner == user_id
        ]
        return sorted(items, key=lambda item: (item.completed_at, item.item.value))

    async def add_item(
        self, user_id: UUID, item: ChecklistItem, source: ItemSource, at: datetime
    ) -> bool:
        key = (user_id, item)
        if key in self._store.onboarding_items:
            return False
        self._store.onboarding_items[key] = CompletedItem(item=item, completed_at=at, source=source)
        return True
