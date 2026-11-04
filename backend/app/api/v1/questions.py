"""Вопросы проекта."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request

from app.api.access import (
    ApiScope,
    ProjectRole,
    ResourceKind,
    ensure_project_access,
    ensure_resource_access,
    require_scope,
    require_token_scope,
    review_lane_ids,
)
from app.api.auth import OptionalUserDep
from app.api.deps import ContainerDep
from app.api.schemas.common import errors
from app.api.schemas.questions import Question, QuestionActionRequest, QuestionAnswerCreate
from app.domain.models import (
    ANSWER_VIA_AGENT,
    QuestionActionKind,
    QuestionCategory,
    QuestionStatus,
)
from app.domain.onboarding import ChecklistItem
from app.services.api_tokens import current_api_token
from app.services.errors import NotFoundError

router = APIRouter(tags=["questions"])


async def _ensure_question_in_review_scope(
    request: Request, container: ContainerDep, question_id: UUID
) -> None:
    """Вопрос вне области проверки неотличим от чужого: `404`, без раскрытия текста."""
    lanes = review_lane_ids(request)
    if lanes is None:
        return
    project_id = await container.access.resource_project_id(ResourceKind.QUESTION, question_id)
    question = await container.questions.get(question_id)
    if not await container.review.question_in_scope(project_id, question, lanes):
        raise NotFoundError("Вопрос не найден")


@router.get(
    "/projects/{project_id}/questions",
    dependencies=[require_scope(ApiScope.PROJECTS_READ)],
    responses=errors(401, 404, 410, 422),
)
async def list_questions(  # noqa: PLR0917 — сигнатура FastAPI-эндпоинта
    project_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
    status: Annotated[QuestionStatus | None, Query()] = None,
    category: Annotated[QuestionCategory | None, Query()] = None,
) -> list[Question]:
    """Вопросы проекта: `category=technical` — отдельная вкладка технических вопросов."""
    role = await ensure_project_access(request, container, project_id, user, write=False)
    questions = await container.questions.list(project_id, status=status, category=category)
    lanes = review_lane_ids(request)
    if lanes is not None and role is ProjectRole.REVIEWER:
        questions = await container.review.filter_questions(project_id, questions, lanes)
    return [Question.model_validate(q) for q in questions]


@router.post(
    "/questions/{question_id}/answer",
    dependencies=[require_scope(ApiScope.QUESTIONS_ANSWER)],
    responses=errors(401, 403, 404, 409, 410, 422),
)
async def answer_question(
    question_id: UUID,
    body: QuestionAnswerCreate,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> Question:
    """Ответ создаёт источник `kind=answer`; вопрос становится `answered`.
    Следующий прогон подтвердит ответ (`resolved`) или вернёт вопрос (`open`)."""
    await ensure_resource_access(
        request,
        container,
        question_id,
        user,
        resource=ResourceKind.QUESTION,
        write=True,
        allow_reviewer=True,
    )
    await _ensure_question_in_review_scope(request, container, question_id)
    token = current_api_token(request)
    answered = await container.questions.answer(
        question_id,
        text=body.text,
        via=ANSWER_VIA_AGENT if token is not None else None,
        via_name=token.name if token is not None else None,
        share_link_id=token.share_link_id if token is not None else None,
    )
    await container.onboarding.record(user.id if user else None, ChecklistItem.QUESTION_ANSWERED)
    return Question.model_validate(answered)


@router.post(
    "/questions/{question_id}/ignore",
    dependencies=[require_scope(ApiScope.QUESTIONS_ANSWER)],
    responses=errors(401, 403, 404, 409, 410, 422),
)
async def ignore_question(
    question_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> Question:
    """Принять допущение: вопрос `ignored`, допущение попадёт в схему и отчёт."""
    await ensure_resource_access(
        request,
        container,
        question_id,
        user,
        resource=ResourceKind.QUESTION,
        write=True,
        allow_reviewer=True,
    )
    await _ensure_question_in_review_scope(request, container, question_id)
    ignored = await container.questions.ignore(question_id)
    await container.onboarding.record(user.id if user else None, ChecklistItem.ASSUMPTION_ACCEPTED)
    return Question.model_validate(ignored)


@router.post(
    "/questions/{question_id}/reopen",
    dependencies=[require_scope(ApiScope.QUESTIONS_ANSWER)],
    responses=errors(401, 403, 404, 409, 410, 422),
)
async def reopen_question(
    question_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> Question:
    """Вернуть проигнорированный или отвеченный вопрос в `open` (ответ выключается)."""
    await ensure_resource_access(
        request, container, question_id, user, resource=ResourceKind.QUESTION, write=True
    )
    return Question.model_validate(await container.questions.reopen(question_id))


@router.post(
    "/questions/{question_id}/actions",
    dependencies=[require_scope(ApiScope.QUESTIONS_ANSWER)],
    responses=errors(401, 403, 404, 409, 410, 422),
)
async def apply_question_action(
    question_id: UUID,
    body: QuestionActionRequest,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> Question:
    """Действие по техническому вопросу: настройки, повтор, продолжить без этого, бюджет.

    Действия с прогоном (`retry`, `continue_without`, `raise_budget`) продолжают ожидающий
    прогон и поэтому по токену доступа требуют ещё и право `runs:start`.
    """
    await ensure_resource_access(
        request, container, question_id, user, resource=ResourceKind.QUESTION, write=True
    )
    if body.action is not QuestionActionKind.OPEN_SETTINGS:
        require_token_scope(request, ApiScope.RUNS_START)
    question = await container.technical_questions.apply_action(
        question_id,
        body.action,
        budget=body.budget.to_domain() if body.budget is not None else None,
    )
    return Question.model_validate(question)
