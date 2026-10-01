"""Вопросы проекта."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import ContainerDep
from app.api.schemas.common import errors
from app.api.schemas.questions import Question, QuestionAnswerCreate
from app.domain.models import QuestionStatus

router = APIRouter(tags=["questions"])


@router.get("/projects/{project_id}/questions", responses=errors(404, 422))
async def list_questions(
    project_id: UUID,
    container: ContainerDep,
    status: Annotated[QuestionStatus | None, Query()] = None,
) -> list[Question]:
    questions = await container.questions.list(project_id, status=status)
    return [Question.model_validate(q) for q in questions]


@router.post("/questions/{question_id}/answer", responses=errors(404, 409, 422))
async def answer_question(
    question_id: UUID, body: QuestionAnswerCreate, container: ContainerDep
) -> Question:
    """Ответ создаёт источник `kind=answer`; вопрос становится `answered`.
    Следующий прогон подтвердит ответ (`resolved`) или вернёт вопрос (`open`)."""
    return Question.model_validate(await container.questions.answer(question_id, text=body.text))


@router.post("/questions/{question_id}/ignore", responses=errors(404, 409, 422))
async def ignore_question(question_id: UUID, container: ContainerDep) -> Question:
    """Принять допущение: вопрос `ignored`, допущение попадёт в схему и отчёт."""
    return Question.model_validate(await container.questions.ignore(question_id))


@router.post("/questions/{question_id}/reopen", responses=errors(404, 409, 422))
async def reopen_question(question_id: UUID, container: ContainerDep) -> Question:
    """Вернуть проигнорированный или отвеченный вопрос в `open` (ответ выключается)."""
    return Question.model_validate(await container.questions.reopen(question_id))
