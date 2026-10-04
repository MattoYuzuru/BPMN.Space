"""Вопросы проекта."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request

from app.api.access import ResourceKind, ensure_project_access, ensure_resource_access
from app.api.auth import OptionalUserDep
from app.api.deps import ContainerDep
from app.api.schemas.common import errors
from app.api.schemas.questions import Question, QuestionAnswerCreate
from app.domain.models import QuestionStatus

router = APIRouter(tags=["questions"])


@router.get("/projects/{project_id}/questions", responses=errors(401, 404, 422))
async def list_questions(
    project_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
    status: Annotated[QuestionStatus | None, Query()] = None,
) -> list[Question]:
    await ensure_project_access(request, container, project_id, user, write=False)
    questions = await container.questions.list(project_id, status=status)
    return [Question.model_validate(q) for q in questions]


@router.post("/questions/{question_id}/answer", responses=errors(401, 403, 404, 409, 422))
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
        request, container, question_id, user, resource=ResourceKind.QUESTION, write=True
    )
    return Question.model_validate(await container.questions.answer(question_id, text=body.text))


@router.post("/questions/{question_id}/ignore", responses=errors(401, 403, 404, 409, 422))
async def ignore_question(
    question_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> Question:
    """Принять допущение: вопрос `ignored`, допущение попадёт в схему и отчёт."""
    await ensure_resource_access(
        request, container, question_id, user, resource=ResourceKind.QUESTION, write=True
    )
    return Question.model_validate(await container.questions.ignore(question_id))


@router.post("/questions/{question_id}/reopen", responses=errors(401, 403, 404, 409, 422))
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
