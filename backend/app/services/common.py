"""Общее для сервисов: часы и генератор id (подменяются в тестах), загрузка с проверкой 404."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from app.domain.models import Project, Question, Run, Source, Version
from app.infra.repositories.base import Repositories
from app.services.errors import NotFoundError, PayloadTooLargeError


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Runtime:
    """Часы и id: в продакшене — системные, в тестах — детерминированные."""

    clock: Callable[[], datetime] = field(default=utc_now)
    new_id: Callable[[], UUID] = field(default=uuid.uuid4)


async def get_project(repos: Repositories, project_id: UUID) -> Project:
    project = await repos.projects.get(project_id)
    if project is None:
        raise NotFoundError("Проект не найден")
    return project


async def get_source(repos: Repositories, source_id: UUID) -> Source:
    source = await repos.sources.get(source_id)
    if source is None:
        raise NotFoundError("Источник не найден")
    return source


async def get_question(repos: Repositories, question_id: UUID) -> Question:
    question = await repos.questions.get(question_id)
    if question is None:
        raise NotFoundError("Вопрос не найден")
    return question


async def get_run(repos: Repositories, run_id: UUID) -> Run:
    run = await repos.runs.get(run_id)
    if run is None:
        raise NotFoundError("Прогон не найден")
    return run


async def get_version(repos: Repositories, version_id: UUID) -> Version:
    version = await repos.versions.get(version_id)
    if version is None:
        raise NotFoundError("Версия схемы не найдена")
    return version


async def touch_project(repos: Repositories, project_id: UUID, at: datetime) -> None:
    """Любое изменение внутри проекта поднимает его в начало списка."""
    await repos.projects.touch(project_id, at)


def too_large(subject: str, limit_bytes: int) -> PayloadTooLargeError:
    """413 с лимитом в мегабайтах: «Файл больше 20 МБ»."""
    limit_mb = max(limit_bytes // (1024 * 1024), 1)
    return PayloadTooLargeError(f"{subject} больше {limit_mb} МБ")
