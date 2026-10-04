"""Интерфейсы репозиториев. В приложении используется SQL-реализация, в тестах — in-memory."""

from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager, nullcontext
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.domain.access import ProjectMember, ProjectRole, ResourceKind, ShareLink
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

type PageKey = tuple[datetime, UUID]


class ActiveRunConflictError(Exception):
    """В БД уже есть активный прогон этого проекта (гарантия уникального индекса)."""


class ProjectRepository(Protocol):
    async def add(
        self, project: Project, *, owner_id: UUID | None = None, public: bool = False
    ) -> None:
        """`public=True` — демо-проект, доступный всем вошедшим на чтение (только сид)."""
        ...

    async def get(self, project_id: UUID) -> Project | None: ...
    async def update(self, project: Project) -> None:
        """Меняет только название и описание (`updated_at` — через `touch`)."""
        ...

    async def touch(self, project_id: UUID, at: datetime) -> None:
        """Поднимает `updated_at` до `at`, если он меньше. Остальные поля не трогает."""
        ...

    async def lock(self, project_id: UUID) -> Project | None:
        """Блокирует проект до конца транзакции (`SELECT … FOR UPDATE`), `None` — проекта нет.

        Сериализует действия, которым нужен единый порядок внутри проекта: нумерацию версий,
        запуск прогона, ручное сохранение схемы, удаление. Вне `Repositories.atomic()`
        блокировка снимается сразу.
        """
        ...

    async def delete(self, project_id: UUID) -> None:
        """Удаляет проект вместе с источниками, вопросами, прогонами и версиями."""
        ...

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
    async def patch(
        self,
        source_id: UUID,
        changes: Mapping[str, Any],
        *,
        only_status: SourceStatus | None = None,
    ) -> bool:
        """Точечно меняет перечисленные поля (`title`, `content`, `status`, `active`, `error`).

        Остальные поля не перезаписываются: пользователь мог изменить их параллельно с фоновым
        разбором. `only_status` — менять, только если источник сейчас в этом статусе.
        `False` — источника нет или статус уже другой.
        """
        ...

    async def delete(self, source_id: UUID) -> None: ...
    async def list_by_project(self, project_id: UUID) -> list[Source]:
        """Источники проекта по возрастанию `created_at`."""
        ...

    async def fail_processing(self, error: str) -> int:
        """Все источники в `processing` → `failed` с причиной `error`; возвращает их число."""
        ...


class QuestionRepository(Protocol):
    async def add(self, question: Question) -> None: ...
    async def get(self, question_id: UUID) -> Question | None: ...
    async def update(self, question: Question) -> None: ...
    async def list_by_project(
        self, project_id: UUID, *, status: QuestionStatus | None = None
    ) -> list[Question]:
        """Вопросы проекта в порядке кодов (Q-1, Q-2, …)."""
        ...


class RunRepository(Protocol):
    async def add(self, run: Run) -> None: ...
    async def get(self, run_id: UUID) -> Run | None: ...
    async def update(self, run: Run) -> None: ...
    async def list_by_project(self, project_id: UUID) -> list[Run]:
        """Прогоны проекта по возрастанию `started_at`."""
        ...

    async def active_for_project(self, project_id: UUID) -> Run | None: ...


class VersionRepository(Protocol):
    async def add(self, version: Version) -> None: ...
    async def get(self, version_id: UUID) -> Version | None: ...
    async def list_by_project(self, project_id: UUID) -> list[Version]:
        """Версии проекта по убыванию номера (последняя — первой)."""
        ...

    async def latest(self, project_id: UUID) -> Version | None: ...


class LlmCallRepository(Protocol):
    async def add(self, call: LlmCall) -> None: ...


class AccessRepository(Protocol):
    """Роли пользователей, участники и ссылки доступа. Есть только у PostgreSQL-хранилища."""

    async def project_role(self, project_id: UUID, user_id: UUID) -> ProjectRole | None: ...

    async def project_roles(
        self, project_ids: list[UUID], user_id: UUID | None
    ) -> dict[UUID, ProjectRole]:
        """Роли для страницы проектов двумя запросами; недоступные проекты в ответ не попадают."""
        ...

    async def resource_project_id(self, kind: ResourceKind, resource_id: UUID) -> UUID | None: ...
    async def find_share_link(self, token_hash: str) -> ShareLink | None: ...
    async def add_share_link(self, link: ShareLink) -> None: ...
    async def list_share_links(self, project_id: UUID) -> list[ShareLink]: ...

    async def revoke_share_link(
        self, project_id: UUID, link_id: UUID, revoked_at: datetime
    ) -> bool: ...

    async def list_members(self, project_id: UUID) -> list[ProjectMember]: ...
    async def remove_member(self, project_id: UUID, user_id: UUID) -> bool: ...

    async def add_editor(self, project_id: UUID, user_id: UUID, added_at: datetime) -> None: ...


@dataclass(frozen=True, slots=True)
class Repositories:
    projects: ProjectRepository
    sources: SourceRepository
    questions: QuestionRepository
    runs: RunRepository
    versions: VersionRepository
    llm_calls: LlmCallRepository
    # None в in-memory режиме: аккаунты и ссылки требуют PostgreSQL.
    access: AccessRepository | None = None
    # Открывает транзакцию PostgreSQL; None — репозитории и так атомарны (in-memory).
    transaction: Callable[[], AbstractAsyncContextManager["Repositories"]] | None = None

    def atomic(self) -> AbstractAsyncContextManager["Repositories"]:
        """Единица работы: все вызовы через выданные репозитории — одна транзакция.

        Внутри уже открытой транзакции вложенный `atomic()` возвращает те же репозитории.
        Исключение откатывает всё, выход без ошибки — фиксирует.
        """
        if self.transaction is None:
            return nullcontext(self)
        return self.transaction()
