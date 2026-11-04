"""Технические вопросы (RFC-0006, шаг 2) и точка интеграции для инструментов.

Технический вопрос касается материалов и запуска, а не процесса: на граф он не влияет и в IR
не попадает. Вместо текстового ответа у него действия: открыть настройки, повторить, продолжить
без этого, поднять бюджет. Блокирующий вопрос переводит прогон в `waiting`; после действия
прогон продолжается с того же места (этапы повторяются, повтор не должен платить дважды —
кеш производных появится вместе с волной инструментов).

Сервис — единственная точка создания таких вопросов: квоты, неверный ключ, отсутствующая
возможность и исчерпанный бюджет приходят сюда (волна инструментов вызывает `report_failure`).
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.domain import questions as rules
from app.domain.models import (
    Question,
    QuestionAction,
    QuestionActionKind,
    QuestionCategory,
    QuestionStatus,
    Run,
    Severity,
    TechnicalQuestionKind,
)
from app.domain.questions import default_actions
from app.infra.repositories.base import Repositories
from app.llm.capabilities import Budget
from app.services.common import Runtime, get_project, get_question, touch_project
from app.services.errors import ConflictError, InvalidInputError

MAX_QUESTION_CHARS = 1_000
_CLOSED = frozenset({QuestionStatus.RESOLVED, QuestionStatus.IGNORED, QuestionStatus.OBSOLETE})


class RunActions(Protocol):
    """Что технический вопрос умеет делать с прогоном; реализует `RunService`."""

    async def resume_waiting(self, run_id: UUID) -> Run:
        """Продолжить прогон, ждущий действия пользователя."""
        ...

    async def raise_budget(self, run_id: UUID, budget: Budget) -> Run:
        """Поднять бюджет ждущего прогона и сохранить его в `ir.execution.profile`."""
        ...


@dataclass(frozen=True, slots=True)
class CapabilityFailure:
    """Структурированный отказ инструмента/ключа — вход для технического вопроса (волна C).

    `kind` — класс причины (квота, ключ, возможность, неполный ввод); `text` — что именно
    произошло, для пользователя; `capability` и `provider` помогают открыть нужные настройки.
    """

    kind: TechnicalQuestionKind
    text: str
    capability: str | None = None
    provider: str | None = None
    blocking: bool = True


class TechnicalQuestionService:
    """Создание технических вопросов и действия по ним."""

    def __init__(
        self,
        repos: Repositories,
        *,
        runtime: Runtime,
        run_actions: RunActions | None = None,
    ) -> None:
        self._repos = repos
        self._rt = runtime
        self._run_actions = run_actions

    def bind_run_actions(self, actions: RunActions) -> None:
        """Связывает вопрос с прогонами (вызывает `container.py` после сборки `RunService`)."""
        self._run_actions = actions

    async def create(
        self,
        project_id: UUID,
        kind: TechnicalQuestionKind,
        text: str,
        *,
        run_id: UUID | None = None,
        blocking: bool = True,
        actions: list[QuestionAction] | None = None,
        assumption: str = "",
    ) -> Question:
        """Создаёт технический вопрос с кодом проекта и действиями по типу."""
        await get_project(self._repos, project_id)
        description = text.strip()
        if not description:
            raise InvalidInputError("У технического вопроса должен быть текст")
        now = self._rt.clock()
        async with self._repos.atomic() as repos:
            await repos.projects.lock(project_id)
            questions = await repos.questions.list_by_project(project_id)
            # «Повторить» осмысленно только при связанном прогоне; у вопроса из фоновой
            # обработки медиа прогона нет — действие не предлагаем.
            if actions is None:
                actions = [
                    item
                    for item in default_actions(kind)
                    if run_id is not None or item.kind is not QuestionActionKind.RETRY
                ]
            if run_id is not None:
                # Дубль блокирующего вопроса по тому же прогону не создаём.
                existing = next(
                    (
                        item
                        for item in questions
                        if item.is_technical
                        and item.run_id == run_id
                        and item.kind is kind
                        and item.status is QuestionStatus.OPEN
                    ),
                    None,
                )
                if existing is not None:
                    return existing
            question = Question(
                id=self._rt.new_id(),
                project_id=project_id,
                code=rules.next_code(questions),
                kind=kind,
                severity=Severity.MAJOR,
                status=QuestionStatus.OPEN,
                text=description[:MAX_QUESTION_CHARS],
                assumption=assumption[:MAX_QUESTION_CHARS],
                created_at=now,
                updated_at=now,
                run_id=run_id,
                category=QuestionCategory.TECHNICAL,
                actions=list(actions or []),
                blocking=blocking,
            )
            await repos.questions.add(question)
            await touch_project(repos, project_id, now)
            return question

    async def report_failure(
        self,
        project_id: UUID,
        failure: CapabilityFailure,
        *,
        run_id: UUID | None = None,
    ) -> Question:
        """Точка интеграции волны инструментов: отказ возможности → технический вопрос."""
        return await self.create(
            project_id,
            failure.kind,
            failure.text,
            run_id=run_id,
            blocking=failure.blocking,
        )

    async def apply_action(
        self,
        question_id: UUID,
        action: QuestionActionKind,
        *,
        budget: Budget | None = None,
    ) -> Question:
        """Выполняет действие по техническому вопросу и закрывает его.

        Действия с прогоном (`retry`, `continue_without`, `raise_budget`) идут через
        `RunService`: продолжение берёт те же блокировки проекта, что и запуск.
        """
        question = await get_question(self._repos, question_id)
        if not question.is_technical:
            raise InvalidInputError("Действия доступны только для технических вопросов")
        allowed = {item.kind for item in question.actions}
        if action not in allowed:
            raise InvalidInputError(
                "Это действие недоступно для вопроса. Доступно: "
                + ", ".join(f"«{item.label}»" for item in question.actions)
            )
        if question.status in _CLOSED:
            raise ConflictError(f"Вопрос {question.code} уже закрыт")
        run_id = question.run_id
        if action is QuestionActionKind.RAISE_BUDGET:
            if budget is None:
                raise InvalidInputError("Укажите новый бюджет: токены и/или стоимость в долларах")
            if run_id is not None:
                actions = self._require_run_actions()
                await actions.raise_budget(run_id, budget)
                await actions.resume_waiting(run_id)
            await self._close(question, QuestionStatus.RESOLVED)
            return await self._reload(question)
        if action is QuestionActionKind.CONTINUE_WITHOUT:
            # Сначала продолжение: если прогон уже нельзя продолжить, вопрос остаётся
            # открытым, а не закрытым без результата.
            if run_id is not None:
                await self._require_run_actions().resume_waiting(run_id)
            await self._close(question, QuestionStatus.IGNORED)
            return await self._reload(question)
        if action is QuestionActionKind.RETRY:
            if run_id is None:
                raise ConflictError("Повтор станет доступен, когда вопрос будет связан с прогоном")
            await self._require_run_actions().resume_waiting(run_id)
            await self._close(question, QuestionStatus.RESOLVED)
            return await self._reload(question)
        # «Открыть настройки» выполняется интерфейсом: серверных изменений нет.
        return question

    def _require_run_actions(self) -> RunActions:
        if self._run_actions is None:
            raise ConflictError("Прогон недоступен для действий по этому вопросу")
        return self._run_actions

    async def _close(self, question: Question, status: QuestionStatus) -> None:
        question.status = status
        question.updated_at = self._rt.clock()
        async with self._repos.atomic() as repos:
            await repos.projects.lock(question.project_id)
            await repos.questions.update(question)
            await touch_project(repos, question.project_id, question.updated_at)

    async def _reload(self, question: Question) -> Question:
        return await get_question(self._repos, question.id)


# Порт на будущее: сервисы волны инструментов передают сюда структурированный отказ.
FailureReporter = Callable[[UUID, CapabilityFailure], Awaitable[Question]]
