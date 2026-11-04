"""In-memory реализация репозиториев (mock, #2).

Хранит копии сущностей: изменение объекта без `update()` не попадает в хранилище — так же,
как будет с БД. Данные живут до рестарта процесса.
Нужен для тестов сервисов и локального режима без БД; в приложении с `DATABASE_URL` работает
SQL-реализация (`sql.py`). Операции здесь не прерываются между `await`, поэтому атомарны сами:
`Repositories.atomic()` — пустой контекст, `lock()` ничего не блокирует.
"""

import copy
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from app.domain.access import ProjectScope
from app.domain.api_tokens import ApiToken
from app.domain.credentials import MAX_ERROR_CHARS, Credential
from app.domain.models import (
    LlmCall,
    Project,
    Question,
    QuestionStatus,
    Run,
    RunStatus,
    Source,
    SourceKind,
    SourceStatus,
    Version,
    VersionSummary,
)
from app.domain.onboarding import (
    ChecklistItem,
    CompletedItem,
    ItemSource,
    ProjectFacts,
    TourStatus,
    TourStepKey,
    UserOnboarding,
)
from app.domain.questions import normalize
from app.domain.runs import ACTIVE_STATUSES
from app.domain.sources import descendants
from app.infra.repositories.base import PageKey, ProjectStats, Repositories


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
    credentials: dict[UUID, Credential] = field(default_factory=dict[UUID, Credential])
    api_tokens: dict[UUID, ApiToken] = field(default_factory=dict[UUID, ApiToken])
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
            credentials=InMemoryCredentialRepository(self),
            api_tokens=InMemoryApiTokenRepository(self),
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

    async def stats(self, project_ids: Sequence[UUID]) -> dict[UUID, ProjectStats]:
        store = self._store
        result: dict[UUID, ProjectStats] = {}
        for project_id in project_ids:
            sources = [
                s
                for s in store.sources.values()
                if s.project_id == project_id and s.kind is not SourceKind.ANSWER
            ]
            questions = [q for q in store.questions.values() if q.project_id == project_id]
            versions = [v for v in store.versions.values() if v.project_id == project_id]
            latest = max(versions, key=lambda v: v.number, default=None)
            active = next(
                (
                    r
                    for r in store.runs.values()
                    if r.project_id == project_id and r.status in ACTIVE_STATUSES
                ),
                None,
            )
            result[project_id] = ProjectStats(
                sources=sum(1 for s in sources if s.parent_id is None),
                has_material=any(s.active and s.status is not SourceStatus.FAILED for s in sources),
                questions_open=sum(1 for q in questions if q.status is QuestionStatus.OPEN),
                questions_resolved=sum(1 for q in questions if q.status is QuestionStatus.RESOLVED),
                versions=len(versions),
                lanes=tuple(latest.lanes) if latest else (),
                active_run_mode=active.mode if active else None,
            )
        return result

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
        only_ids: frozenset[UUID] | None = None,
    ) -> list[Project]:
        items = sorted(self._matching(query), key=_sort_key, reverse=True)
        if scope_to_user:
            items = self._visible(items, owner_id, scope)
        if only_ids is not None:
            items = [p for p in items if p.id in only_ids]
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
        only_ids: frozenset[UUID] | None = None,
    ) -> int:
        items = self._matching(query)
        if scope_to_user:
            items = self._visible(items, owner_id, scope)
        if only_ids is not None:
            items = [p for p in items if p.id in only_ids]
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
        unknown = set(changes) - {
            "title",
            "content",
            "status",
            "active",
            "error",
            "warning",
            "unreadable_pages",
            "duration_sec",
            "derivation",
            "edited_by_human",
            "media",
        }
        if unknown:
            raise ValueError(f"Поля источника нельзя менять точечно: {sorted(unknown)}")
        stored = self._items.get(source_id)
        if stored is None or (only_status is not None and stored.status is not only_status):
            return False
        for name, value in changes.items():
            setattr(stored, name, copy.deepcopy(value))
        return True

    async def lock_by_project(self, project_id: UUID) -> list[Source]:
        return await self.list_by_project(project_id)

    async def fail_processing(self, error: str) -> int:
        stuck = [s for s in self._items.values() if s.status is SourceStatus.PROCESSING]
        for source in stuck:
            source.status = SourceStatus.FAILED
            source.error = error
        return len(stuck)

    async def delete(self, source_id: UUID) -> None:
        # Как ON DELETE CASCADE в PostgreSQL: вместе с источником удаляются производные.
        for child in descendants(self._items.values(), source_id):
            self._items.pop(child.id, None)
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

    async def bind_elements(self, question_id: UUID, element_ids: list[str]) -> None:
        stored = self._items.get(question_id)
        if stored is not None:
            stored.element_ids = list(element_ids)

    async def apply_reconciled(
        self,
        question: Question,
        *,
        expected_status: QuestionStatus,
        expected_updated_at: datetime | None = None,
    ) -> bool:
        current = self._items.get(question.id)
        if (
            current is None
            or current.status is not expected_status
            or (expected_updated_at is not None and current.updated_at != expected_updated_at)
        ):
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

    async def last_succeeded_id(self, project_id: UUID) -> UUID | None:
        done = [
            r
            for r in self._items.values()
            if r.project_id == project_id and r.status is RunStatus.SUCCEEDED
        ]
        return max(done, key=lambda r: (r.started_at, r.id)).id if done else None


class InMemoryVersionRepository:
    def __init__(self, store: InMemoryStore) -> None:
        self._items = store.versions
        self._runs = store.runs

    async def add(self, version: Version) -> None:
        self._items[version.id] = copy.deepcopy(version)

    async def get(self, version_id: UUID) -> Version | None:
        item = self._items.get(version_id)
        return copy.deepcopy(item) if item else None

    async def list_by_project(self, project_id: UUID, *, include_xml: bool = True) -> list[Version]:
        items = [v for v in self._items.values() if v.project_id == project_id]
        result = [copy.deepcopy(v) for v in sorted(items, key=lambda v: v.number, reverse=True)]
        if not include_xml:
            for version in result:
                version.xml = ""
        return result

    async def latest(self, project_id: UUID) -> Version | None:
        items = await self.list_by_project(project_id)
        return items[0] if items else None

    async def by_number(self, project_id: UUID, number: int) -> Version | None:
        for item in self._items.values():
            if item.project_id == project_id and item.number == number:
                return copy.deepcopy(item)
        return None

    async def list_page(
        self, project_id: UUID, *, limit: int, before: int | None = None
    ) -> list[VersionSummary]:
        items = await self.list_by_project(project_id, include_xml=False)
        return [v.summary() for v in items if before is None or v.number < before][:limit]

    async def replace(self, old_id: UUID, version: Version) -> None:
        self._items.pop(old_id, None)
        self._items[version.id] = copy.deepcopy(version)

    async def has_dependants(self, version_id: UUID) -> bool:
        return any(run.version_id == version_id for run in self._runs.values())

    async def mark_checkpoint(self, version_id: UUID, label: str | None) -> Version | None:
        item = self._items.get(version_id)
        if item is None:
            return None
        item.checkpoint = True
        if label is not None:
            item.label = label or None
        return copy.deepcopy(item)


class InMemoryLlmCallRepository:
    def __init__(self, store: InMemoryStore) -> None:
        self._items = store.llm_calls

    async def add(self, call: LlmCall) -> None:
        self._items[call.id] = copy.deepcopy(call)


class InMemoryCredentialRepository:
    def __init__(self, store: InMemoryStore) -> None:
        self._items = store.credentials

    async def list_by_user(self, user_id: UUID) -> list[Credential]:
        own = [item for item in self._items.values() if item.user_id == user_id]
        own.sort(
            key=lambda item: (not item.is_default, item.priority, item.created_at, str(item.id))
        )
        return [copy.deepcopy(item) for item in own]

    async def get(self, credential_id: UUID) -> Credential | None:
        item = self._items.get(credential_id)
        return copy.deepcopy(item) if item else None

    async def count(self, user_id: UUID) -> int:
        return sum(1 for item in self._items.values() if item.user_id == user_id)

    async def save(self, credential: Credential) -> None:
        if credential.is_default:
            for item in self._items.values():
                if item.user_id == credential.user_id and item.id != credential.id:
                    item.is_default = False
        self._items[credential.id] = copy.deepcopy(credential)

    async def update_fields(
        self,
        credential_id: UUID,
        *,
        label: str | None = None,
        default_model: str | None = None,
        is_default: bool | None = None,
        clear_default_model: bool = False,
        priority: int | None = None,
        enabled: bool | None = None,
        monthly_limit: dict[str, float] | None = None,
        clear_monthly_limit: bool = False,
    ) -> Credential | None:
        item = self._items.get(credential_id)
        if item is None:
            return None
        if is_default:
            for other in self._items.values():
                if other.user_id == item.user_id and other.id != item.id:
                    other.is_default = False
        if label is not None:
            item.label = label
        if default_model is not None:
            item.default_model = default_model
        elif clear_default_model:
            item.default_model = None
        if is_default is not None:
            item.is_default = is_default
        if priority is not None:
            item.priority = priority
        if enabled is not None:
            item.enabled = enabled
        if monthly_limit is not None:
            item.monthly_limit = dict(monthly_limit)
        elif clear_monthly_limit:
            item.monthly_limit = None
        return copy.deepcopy(item)

    async def delete(self, credential_id: UUID) -> bool:
        return self._items.pop(credential_id, None) is not None

    async def mark_used(
        self,
        credential_id: UUID,
        at: datetime,
        error: str | None,
        *,
        error_code: str | None = None,
    ) -> None:
        item = self._items.get(credential_id)
        if item is not None:
            item.last_used_at = at
            item.last_error = error[:MAX_ERROR_CHARS] if error else None
            item.last_error_code = error_code
            if error is None:
                item.exhausted_until = None

    async def mark_failure(
        self,
        credential_id: UUID,
        at: datetime,
        *,
        error: str,
        error_code: str,
        exhausted_until: datetime | None = None,
        disable: bool = False,
    ) -> None:
        item = self._items.get(credential_id)
        if item is None:
            return
        item.last_used_at = at
        item.last_error = error[:MAX_ERROR_CHARS]
        item.last_error_code = error_code
        item.exhausted_until = exhausted_until
        if disable:
            item.enabled = False


class InMemoryApiTokenRepository:
    def __init__(self, store: InMemoryStore) -> None:
        self._items = store.api_tokens

    async def list_by_user(self, user_id: UUID) -> list[ApiToken]:
        own = [t for t in self._items.values() if t.user_id == user_id and t.revoked_at is None]
        own.sort(key=lambda t: (t.created_at, str(t.id)), reverse=True)
        return [copy.deepcopy(t) for t in own]

    async def get(self, token_id: UUID) -> ApiToken | None:
        item = self._items.get(token_id)
        return copy.deepcopy(item) if item else None

    async def by_hash(self, token_hash: str) -> ApiToken | None:
        item = next((t for t in self._items.values() if t.token_hash == token_hash), None)
        return copy.deepcopy(item) if item else None

    async def add_within_limit(self, token: ApiToken, *, max_active: int) -> bool:
        # Между await нет переключений: подсчёт и вставка атомарны сами.
        active = sum(
            1
            for t in self._items.values()
            if t.user_id == token.user_id and t.is_active(token.created_at)
        )
        if active >= max_active:
            return False
        self._items[token.id] = copy.deepcopy(token)
        return True

    async def revoke(self, token_id: UUID, at: datetime) -> None:
        item = self._items.get(token_id)
        if item is not None and item.revoked_at is None:
            item.revoked_at = at

    async def touch(self, token_id: UUID, at: datetime, *, older_than: datetime) -> None:
        item = self._items.get(token_id)
        if item is not None and (item.last_used_at is None or item.last_used_at < older_than):
            item.last_used_at = at


class InMemoryOnboardingRepository:
    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    async def get(self, user_id: UUID) -> UserOnboarding | None:
        state = self._store.onboarding.get(user_id)
        return copy.deepcopy(state) if state else None

    async def project_facts(self, user_id: UUID, *, limit: int) -> list[ProjectFacts]:
        store = self._store
        own = [
            p
            for p in store.projects.values()
            if store.project_owners.get(p.id) == user_id  # редакторов без аккаунтов (PG) нет
        ]
        own.sort(key=lambda p: (p.updated_at, p.id), reverse=True)
        return [self._facts(project.id, project.updated_at) for project in own[:limit]]

    def _facts(self, project_id: UUID, updated_at: datetime) -> ProjectFacts:
        store = self._store
        sources = [s for s in store.sources.values() if s.project_id == project_id]
        material = [s for s in sources if s.active and s.kind is not SourceKind.ANSWER]
        opened = [
            q
            for q in store.questions.values()
            if q.project_id == project_id and q.status is QuestionStatus.OPEN
        ]
        first_open = min(opened, key=lambda q: (q.created_at, len(q.code), q.code), default=None)
        versions = [v.created_at for v in store.versions.values() if v.project_id == project_id]
        latest = max(versions, default=None)
        return ProjectFacts(
            project_id=project_id,
            updated_at=updated_at,
            owned=True,
            has_sources=any(s.status is not SourceStatus.FAILED for s in material),
            has_ready_sources=any(s.status is SourceStatus.READY for s in material),
            has_diagram=latest is not None,
            open_question_id=first_open.id if first_open else None,
            answered_after_diagram=latest is not None
            and any(s.kind is SourceKind.ANSWER and s.created_at > latest for s in sources),
        )

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
