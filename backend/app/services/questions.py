"""Сценарии вопросов: список, ответ (создаёт источник `answer`), игнор, возврат."""

from uuid import UUID

from app.domain import questions as rules
from app.domain.models import Question, QuestionStatus, Source, SourceKind, SourceStatus
from app.infra.repositories.base import Repositories
from app.services.common import Runtime, get_project, get_question, touch_project
from app.services.errors import ConflictError, InvalidInputError

MAX_ANSWER_CHARS = 20_000


class QuestionService:
    def __init__(self, repos: Repositories, *, runtime: Runtime) -> None:
        self._repos = repos
        self._rt = runtime

    async def list(self, project_id: UUID, *, status: QuestionStatus | None) -> list[Question]:
        await get_project(self._repos, project_id)
        return await self._repos.questions.list_by_project(project_id, status=status)

    async def answer(self, question_id: UUID, *, text: str) -> Question:
        question = await get_question(self._repos, question_id)
        text = text.strip()
        if not text:
            raise InvalidInputError("Ответ не может быть пустым")
        if len(text) > MAX_ANSWER_CHARS:
            raise InvalidInputError(f"Ответ длиннее {MAX_ANSWER_CHARS} символов")
        now = self._rt.clock()
        source = Source(
            id=self._rt.new_id(),
            project_id=question.project_id,
            kind=SourceKind.ANSWER,
            title=f"Ответ на {question.code}",
            content=text,
            status=SourceStatus.READY,
            active=True,
            created_at=now,
            question_id=question.id,
        )
        try:
            rules.answer(question, source_id=source.id, text=text, now=now)
        except rules.QuestionTransitionError as error:
            raise ConflictError(str(error)) from error
        await self._repos.sources.add(source)
        await self._repos.questions.update(question)
        await touch_project(self._repos, question.project_id, now)
        return question

    async def ignore(self, question_id: UUID) -> Question:
        question = await get_question(self._repos, question_id)
        now = self._rt.clock()
        try:
            rules.ignore(question, now=now)
        except rules.QuestionTransitionError as error:
            raise ConflictError(str(error)) from error
        await self._repos.questions.update(question)
        await touch_project(self._repos, question.project_id, now)
        return question

    async def reopen(self, question_id: UUID) -> Question:
        """Вернуть вопрос: для отвеченного источник-ответ выключается, но остаётся в истории."""
        question = await get_question(self._repos, question_id)
        now = self._rt.clock()
        try:
            answer_source_id = rules.reopen(question, now=now)
        except rules.QuestionTransitionError as error:
            raise ConflictError(str(error)) from error
        if answer_source_id is not None:
            await self._repos.sources.patch(answer_source_id, {"active": False})
        await self._repos.questions.update(question)
        await touch_project(self._repos, question.project_id, now)
        return question
