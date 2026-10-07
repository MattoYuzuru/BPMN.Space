"""Интерфейсы репозиториев. В приложении используется SQL-реализация, в тестах — in-memory."""

from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager, nullcontext
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.domain.access import ProjectMember, ProjectRole, ProjectScope, ResourceKind, ShareLink
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
    ProjectFacts,
    TourStatus,
    TourStepKey,
    UserOnboarding,
)

type PageKey = tuple[datetime, UUID]


class AccessLinkUnavailableError(Exception):
    """Приглашение отозвано или истекло до фиксации членства."""

    def __init__(self, *, expired: bool) -> None:
        self.expired = expired


class AccessProjectMissingError(Exception):
    """Проект удалён между проверкой ссылки и изменением состава участников."""


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

    async def owner_of(self, project_id: UUID) -> UUID | None:
        """Владелец проекта; `None` — проекта нет, демо-проект или аккаунтов нет."""
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
        scope: ProjectScope = ProjectScope.ALL,
    ) -> list[Project]:
        """Проекты по убыванию (`updated_at`, `id`), строго после ключа `after`.

        `query` — подстрока названия без учёта регистра и «ё».
        """
        ...

    async def count(
        self,
        *,
        query: str | None,
        owner_id: UUID | None = None,
        scope_to_user: bool = False,
        scope: ProjectScope = ProjectScope.ALL,
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

    async def lock_by_project(self, project_id: UUID) -> list[Source]:
        """Свежие источники под row lock; вызывается внутри Repositories.atomic()."""
        ...

    async def fail_processing(self, error: str) -> int:
        """Все источники в `processing` → `failed` с причиной `error`; возвращает их число."""
        ...


class QuestionRepository(Protocol):
    async def add(self, question: Question) -> None: ...
    async def get(self, question_id: UUID) -> Question | None: ...
    async def update(self, question: Question) -> None: ...
    async def bind_elements(self, question_id: UUID, element_ids: list[str]) -> None:
        """Меняет только связи с диаграммой, не перезаписывая статус, ответ или доказательство."""
        ...

    async def apply_reconciled(
        self,
        question: Question,
        *,
        expected_status: QuestionStatus,
        expected_updated_at: datetime | None = None,
    ) -> bool:
        """Точечно записывает поля сверки, если статус и версия вопроса не менялись.

        Возвращает `False`, если вопрос удалён или его статус уже изменён (например, аналитик
        ответил между чтением и записью): чужая правка не затирается.
        """
        ...

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
    async def list_by_project(self, project_id: UUID, *, include_xml: bool = True) -> list[Version]:
        """Версии по убыванию номера; include_xml=False исключает данные XML из чтения."""
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
    async def deleted_access(self, key_hash: str) -> bool: ...
    async def find_share_link(self, token_hash: str) -> ShareLink | None: ...
    async def get_share_link(self, link_id: UUID) -> ShareLink | None: ...
    async def add_share_link(self, link: ShareLink) -> None: ...
    async def list_share_links(self, project_id: UUID) -> list[ShareLink]: ...

    async def revoke_share_link(
        self, project_id: UUID, link_id: UUID, revoked_at: datetime
    ) -> bool: ...

    async def list_members(self, project_id: UUID) -> list[ProjectMember]: ...
    async def remove_member(self, project_id: UUID, user_id: UUID) -> bool: ...

    async def add_member(
        self,
        project_id: UUID,
        user_id: UUID,
        role: ProjectRole,
        added_at: datetime,
        *,
        link_id: UUID | None = None,
    ) -> None: ...


class OnboardingRepository(Protocol):
    """Состояние тура и отмеченные пункты чек-листа пользователя."""

    async def get(self, user_id: UUID) -> UserOnboarding | None: ...

    async def get_or_create(self, user_id: UUID, now: datetime) -> UserOnboarding:
        """Строка пользователя; при первом обращении создаётся (`pending`, чек-лист виден).

        Сначала чтение, вставка — только если строки нет.
        """
        ...

    async def project_facts(self, user_id: UUID, *, limit: int) -> list[ProjectFacts]:
        """Факты по проектам, которые пользователь может править (свои и где он редактор).

        Не больше `limit` самых свежих проектов, одним запросом и без текстов источников и XML.
        Демо-проекты только для чтения не входят.
        """
        ...

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
        """Записывает тур, только если статус всё ещё `expected_status` (`False` — не совпал)."""
        ...

    async def set_checklist_hidden(self, user_id: UUID, hidden: bool, now: datetime) -> None: ...
    async def list_items(self, user_id: UUID) -> list[CompletedItem]:
        """Отмеченные пункты по времени отметки."""
        ...

    async def add_item(
        self, user_id: UUID, item: ChecklistItem, source: ItemSource, at: datetime
    ) -> bool:
        """Отмечает пункт, если не отмечен; `True` — впервые, повтор ничего не меняет."""
        ...


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
    # None, если хранилище не умеет онбординг; обе реализации (SQL и in-memory) его дают.
    onboarding: OnboardingRepository | None = None
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
