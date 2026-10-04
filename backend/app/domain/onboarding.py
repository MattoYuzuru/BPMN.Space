"""Онбординг: тур, чек-лист «Начало работы» и выбор места, куда вести по пункту.

Чистые правила без I/O. Порядок и ветвления шагов тура — забота фронтенда: бэкенд хранит
состояние, проверяет, что ключ шага известен, и разрешает только допустимые смены статуса.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class TourStatus(StrEnum):
    PENDING = "pending"  # тур ещё не предлагали
    ACTIVE = "active"  # идёт
    COMPLETED = "completed"
    DISMISSED = "dismissed"


class ItemSource(StrEnum):
    """Кто отметил пункт: сервер при действии или клиент (то, чего сервер не видит)."""

    SERVER = "server"
    CLIENT = "client"


class ChecklistItem(StrEnum):
    """12 пунктов чек-листа в порядке показа (группы: источники, анализ, схема, команда)."""

    PROJECT_CREATED = "project_created"
    TEXT_SOURCE_ADDED = "text_source_added"
    DOCUMENT_UPLOADED = "document_uploaded"
    VOICE_ADDED = "voice_added"
    DIAGRAM_BUILT = "diagram_built"
    QUESTION_ANSWERED = "question_answered"
    ASSUMPTION_ACCEPTED = "assumption_accepted"
    DIAGRAM_REBUILT = "diagram_rebuilt"
    DIAGRAM_EDITED = "diagram_edited"
    SIMULATION_RUN = "simulation_run"
    DIAGRAM_EXPORTED = "diagram_exported"
    PROJECT_SHARED = "project_shared"


# Эти пункты сервер не видит (симуляция токена, скачивание файла), их сообщает клиент.
CLIENT_REPORTABLE = frozenset({ChecklistItem.SIMULATION_RUN, ChecklistItem.DIAGRAM_EXPORTED})


class TourStepKey(StrEnum):
    """11 шагов тура. Бэкенд знает только ключи; последовательность определяет фронтенд."""

    PROJECT_CREATE = "project.create"
    SOURCES_SAMPLE = "sources.sample"
    SOURCES_TEXT = "sources.text"
    SOURCES_VOICE = "sources.voice"
    RUN_START = "run.start"
    RUN_WAIT = "run.wait"
    QUESTION_ANSWER = "question.answer"
    QUESTION_IGNORE = "question.ignore"
    DIAGRAM_TOUR = "diagram.tour"
    SHARE_CREATE = "share.create"
    FINISH = "finish"


FIRST_STEP = TourStepKey.PROJECT_CREATE

_TRANSITIONS: dict[TourStatus, frozenset[TourStatus]] = {
    TourStatus.PENDING: frozenset({TourStatus.ACTIVE, TourStatus.DISMISSED}),
    TourStatus.ACTIVE: frozenset({TourStatus.ACTIVE, TourStatus.COMPLETED, TourStatus.DISMISSED}),
    TourStatus.COMPLETED: frozenset(),
    TourStatus.DISMISSED: frozenset(),
}


class TourTransitionError(ValueError):
    """Недопустимая смена статуса тура. Сообщение — для пользователя."""


def check_transition(current: TourStatus, target: TourStatus, *, restart: bool = False) -> None:
    """Проверяет смену статуса тура.

    `pending → active | dismissed`; `active → active (смена шага) | completed | dismissed`;
    из `completed` и `dismissed` в `active` — только перезапуском (`restart=True`), который
    допустим и из любого другого статуса (например, «Начать заново», когда учебный проект удалён).
    """
    if restart:
        if target is not TourStatus.ACTIVE:
            raise TourTransitionError("Перезапуск начинает тур заново")
        return
    if target not in _TRANSITIONS[current]:
        raise TourTransitionError(f"Из состояния «{current.value}» в «{target.value}» не перейти")


@dataclass(slots=True, kw_only=True)
class UserOnboarding:
    """Состояние онбординга пользователя (одна строка на пользователя)."""

    user_id: UUID
    tour_status: TourStatus
    tour_step: TourStepKey | None
    tour_project_id: UUID | None
    checklist_hidden: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class CompletedItem:
    item: ChecklistItem
    completed_at: datetime
    source: ItemSource


class TargetRoute(StrEnum):
    PROJECTS = "projects"
    WORKSPACE = "workspace"


class TargetHint(StrEnum):
    """Что показать пользователю: сделать пункт здесь или сначала подготовить предыдущий шаг."""

    DO_ITEM = "do_item"
    NEED_PROJECT = "need_project"
    NEED_SOURCE = "need_source"
    NEED_DIAGRAM = "need_diagram"
    NEED_QUESTIONS = "need_questions"


@dataclass(frozen=True, slots=True, kw_only=True)
class Target:
    """Куда вести по невыполненному пункту. Якорь и тексты подсказок выбирает фронтенд."""

    route: TargetRoute
    hint: TargetHint
    project_id: UUID | None = None
    question_id: UUID | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectFacts:
    """Снимок проекта, который пользователь может редактировать (для `resolve_target`)."""

    project_id: UUID
    updated_at: datetime
    owned: bool  # свой проект; редактор по ссылке — False
    has_sources: bool  # есть источники (не ответы): готовые или в разборе
    has_ready_sources: bool  # есть готовые источники — по ним можно строить схему
    has_diagram: bool
    open_question_id: UUID | None  # самый ранний открытый вопрос
    answered_after_diagram: bool  # после последней версии схемы появился ответ


type _Match = Callable[[ProjectFacts], bool]


def _projects_screen(hint: TargetHint = TargetHint.NEED_PROJECT) -> Target:
    return Target(route=TargetRoute.PROJECTS, hint=hint)


def _workspace(
    project: ProjectFacts, hint: TargetHint, *, question_id: UUID | None = None
) -> Target:
    return Target(
        route=TargetRoute.WORKSPACE,
        hint=hint,
        project_id=project.project_id,
        question_id=question_id,
    )


def _first(projects: Sequence[ProjectFacts], match: _Match) -> ProjectFacts | None:
    return next((project for project in projects if match(project)), None)


def _buildable(project: ProjectFacts) -> bool:
    return project.has_ready_sources and not project.has_diagram


def _to_diagram_prerequisite(projects: Sequence[ProjectFacts]) -> Target:
    """Куда вести, если схемы нет: проект, где её можно построить, иначе — добавить источник."""
    project = _first(projects, _buildable) or _first(projects, lambda p: p.has_sources)
    if project is not None:
        return _workspace(project, TargetHint.NEED_DIAGRAM)
    if projects:
        return _workspace(projects[0], TargetHint.NEED_SOURCE)
    return _projects_screen()


def _to_questions(projects: Sequence[ProjectFacts]) -> Target:
    project = _first(projects, lambda p: p.open_question_id is not None)
    if project is not None:
        return _workspace(project, TargetHint.DO_ITEM, question_id=project.open_question_id)
    project = _first(projects, lambda p: p.has_sources)
    if project is not None:
        return _workspace(project, TargetHint.NEED_QUESTIONS)
    if projects:
        return _workspace(projects[0], TargetHint.NEED_SOURCE)
    return _projects_screen()


def _to_project_screen(_: Sequence[ProjectFacts]) -> Target:
    return _projects_screen(TargetHint.DO_ITEM)


def _to_latest(projects: Sequence[ProjectFacts]) -> Target:
    if projects:
        return _workspace(projects[0], TargetHint.DO_ITEM)
    return _projects_screen()


def _to_build(projects: Sequence[ProjectFacts]) -> Target:
    project = _first(projects, _buildable) or _first(projects, lambda p: p.has_sources)
    if project is not None:
        return _workspace(project, TargetHint.DO_ITEM)
    if projects:
        return _workspace(projects[0], TargetHint.NEED_SOURCE)
    return _projects_screen()


def _to_rebuild(projects: Sequence[ProjectFacts]) -> Target:
    project = _first(projects, lambda p: p.has_diagram and p.answered_after_diagram)
    if project is not None:
        return _workspace(project, TargetHint.DO_ITEM)
    return _to_questions(projects)


def _to_diagram(projects: Sequence[ProjectFacts]) -> Target:
    project = _first(projects, lambda p: p.has_diagram)
    if project is not None:
        return _workspace(project, TargetHint.DO_ITEM)
    return _to_diagram_prerequisite(projects)


def _to_own(projects: Sequence[ProjectFacts]) -> Target:
    project = _first(projects, lambda p: p.owned)
    if project is not None:
        return _workspace(project, TargetHint.DO_ITEM)
    return _projects_screen()


_RESOLVERS: dict[ChecklistItem, Callable[[Sequence[ProjectFacts]], Target]] = {
    ChecklistItem.PROJECT_CREATED: _to_project_screen,
    ChecklistItem.TEXT_SOURCE_ADDED: _to_latest,
    ChecklistItem.DOCUMENT_UPLOADED: _to_latest,
    ChecklistItem.VOICE_ADDED: _to_latest,
    ChecklistItem.DIAGRAM_BUILT: _to_build,
    ChecklistItem.QUESTION_ANSWERED: _to_questions,
    ChecklistItem.ASSUMPTION_ACCEPTED: _to_questions,
    ChecklistItem.DIAGRAM_REBUILT: _to_rebuild,
    ChecklistItem.DIAGRAM_EDITED: _to_diagram,
    ChecklistItem.SIMULATION_RUN: _to_diagram,
    ChecklistItem.DIAGRAM_EXPORTED: _to_diagram,
    ChecklistItem.PROJECT_SHARED: _to_own,
}


def resolve_target(item: ChecklistItem, projects: Sequence[ProjectFacts]) -> Target:
    """Куда вести по пункту чек-листа. `projects` — проекты, доступные пользователю на правку.

    Демо-проекты только для чтения в снимок не попадают. Проекты сортируются здесь:
    «последний» — с самым свежим `updated_at`.
    """
    latest_first = sorted(projects, key=lambda p: (p.updated_at, p.project_id), reverse=True)
    return _RESOLVERS[item](latest_first)
