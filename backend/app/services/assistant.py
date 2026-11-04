"""Диалоговый помощник проекта на базе настроенного LLM-провайдера."""

from typing import cast
from uuid import UUID

from app.domain.models import QuestionStatus
from app.infra.repositories.base import Repositories
from app.llm.pipeline import LlmPipeline
from app.services.common import get_project
from app.services.model_resolver import ModelResolver


class AssistantService:
    def __init__(self, repos: Repositories, *, resolver: ModelResolver) -> None:
        self._repos = repos
        self._resolver = resolver

    async def reply(
        self,
        project_id: UUID,
        *,
        message: str,
        diagram_xml: str,
        history: list[dict[str, str]],
        user_id: UUID | None = None,
        credential_id: UUID | None = None,
        model: str | None = None,
    ) -> str:
        project = await get_project(self._repos, project_id)
        source_items = await self._repos.sources.list_by_project(project_id)
        question_items = await self._repos.questions.list_by_project(
            project_id, status=QuestionStatus.OPEN
        )
        sources: list[dict[str, str]] = []
        budget = 24_000
        for source in source_items:
            # Та же выборка, что у прогона: запись без текста и краткие содержания не идут.
            if not source.feeds_model or budget <= 0:
                continue
            content = source.content[:budget]
            budget -= len(content)
            sources.append({"title": source.title[:200], "text": content})
        questions = [
            {"code": item.code[:40], "text": item.text[:1000], "assumption": item.assumption[:1000]}
            for item in question_items[:12]
        ]
        return await self._reply_with_context(
            project_title=project.title,
            project_description=project.description,
            sources=sources,
            diagram_xml=diagram_xml,
            history=history,
            message=message,
            questions=questions,
            user_id=user_id,
            credential_id=credential_id,
            model=model,
        )

    async def reply_local(
        self,
        *,
        project_title: str,
        source: str,
        diagram_xml: str,
        history: list[dict[str, str]],
        message: str,
        user_id: UUID | None = None,
        credential_id: UUID | None = None,
        model: str | None = None,
    ) -> str:
        """Ответить по браузерному черновику, не сохраняя его на сервере."""
        return await self._reply_with_context(
            project_title=project_title,
            project_description=None,
            sources=[{"title": "Описание процесса", "text": source[:24_000]}]
            if source.strip()
            else [],
            questions=[],
            diagram_xml=diagram_xml,
            history=history,
            message=message,
            user_id=user_id,
            credential_id=credential_id,
            model=model,
        )

    async def _reply_with_context(
        self,
        *,
        project_title: str,
        project_description: str | None,
        sources: list[dict[str, str]],
        questions: list[dict[str, str]],
        diagram_xml: str,
        history: list[dict[str, str]],
        message: str,
        user_id: UUID | None,
        credential_id: UUID | None,
        model: str | None,
    ) -> str:
        resolved = await self._resolver.resolve(
            user_id, credential_id=credential_id, model=model, allow_mock=False
        )
        try:
            answer = await cast(
                LlmPipeline, resolved.pipeline
            ).chat(  # allow_mock=False: всегда реальный
                project_title=project_title,
                project_description=project_description,
                sources=sources,
                questions=questions,
                diagram_xml=diagram_xml,
                history=history,
                message=message,
            )
        except Exception as error:
            await self._resolver.mark(resolved.credential_id, str(error))
            raise
        finally:
            await resolved.release()
        await self._resolver.mark(resolved.credential_id, None)
        return answer
