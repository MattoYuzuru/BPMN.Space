"""Интерфейсы репозиториев. В приложении используется SQL-реализация, в тестах — in-memory."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.models import LlmCall, Project, Question, QuestionStatus, Run, Source, Version

type PageKey = tuple[datetime, UUID]


class ActiveRunConflictError(Exception):
    """В БД уже есть активный прогон этого проекта (гарантия уникального индекса)."""


class ProjectRepository(Protocol):
    async def add(self, project: Project, *, owner_id: UUID | None = None) -> None: ...
    async def get(self, project_id: UUID) -> Project | None: ...
    async def update(self, project: Project) -> None: ...
    async def delete(self, project_id: UUID) -> None: ...

    async def list_page(
        self,
        *,
        query: str | None,
        after: PageKey | None,
        limit: int,
        owner_id: UUID | None = None,
        scope_to_user: bool = False,
    ) -> list[Project]:
        """Проекты по убыванию (`updated_at`, `id`), строго после ключа `after`.

        `query` — подстрока названия без учёта регистра и «ё».
        """
        ...

    async def count(
        self, *, query: str | None, owner_id: UUID | None = None, scope_to_user: bool = False
    ) -> int: ...


class SourceRepository(Protocol):
    async def add(self, source: Source) -> None: ...
    async def get(self, source_id: UUID) -> Source | None: ...
    async def update(self, source: Source) -> None: ...
    async def delete(self, source_id: UUID) -> None: ...
    async def list_by_project(self, project_id: UUID) -> list[Source]:
        """Источники проекта по возрастанию `created_at`."""
        ...

    async def delete_by_project(self, project_id: UUID) -> None: ...


class QuestionRepository(Protocol):
    async def add(self, question: Question) -> None: ...
    async def get(self, question_id: UUID) -> Question | None: ...
    async def update(self, question: Question) -> None: ...
    async def list_by_project(
        self, project_id: UUID, *, status: QuestionStatus | None = None
    ) -> list[Question]:
        """Вопросы проекта в порядке кодов (Q-1, Q-2, …)."""
        ...

    async def delete_by_project(self, project_id: UUID) -> None: ...


class RunRepository(Protocol):
    async def add(self, run: Run) -> None: ...
    async def get(self, run_id: UUID) -> Run | None: ...
    async def update(self, run: Run) -> None: ...
    async def list_by_project(self, project_id: UUID) -> list[Run]:
        """Прогоны проекта по возрастанию `started_at`."""
        ...

    async def active_for_project(self, project_id: UUID) -> Run | None: ...
    async def delete_by_project(self, project_id: UUID) -> None: ...


class VersionRepository(Protocol):
    async def add(self, version: Version) -> None: ...
    async def get(self, version_id: UUID) -> Version | None: ...
    async def list_by_project(self, project_id: UUID) -> list[Version]:
        """Версии проекта по убыванию номера (последняя — первой)."""
        ...

    async def latest(self, project_id: UUID) -> Version | None: ...
    async def delete_by_project(self, project_id: UUID) -> None: ...


class LlmCallRepository(Protocol):
    async def add(self, call: LlmCall) -> None: ...


@dataclass(frozen=True, slots=True)
class Repositories:
    projects: ProjectRepository
    sources: SourceRepository
    questions: QuestionRepository
    runs: RunRepository
    versions: VersionRepository
    llm_calls: LlmCallRepository
