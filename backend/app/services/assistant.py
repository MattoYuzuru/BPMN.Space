"""Диалоговый помощник проекта на базе настроенного LLM-провайдера."""

from typing import Protocol
from uuid import UUID

from app.domain.models import QuestionStatus, SourceStatus
from app.infra.repositories.base import Repositories
from app.services.common import get_project


class AssistantModel(Protocol):
    async def chat(
        self,
        *,
        project_title: str,
        project_description: str | None,
        sources: list[dict[str, str]],
        questions: list[dict[str, str]],
        diagram_xml: str,
        history: list[dict[str, str]],
        message: str,
    ) -> str: ...


class AssistantService:
    def __init__(self, repos: Repositories, *, model: AssistantModel) -> None:
        self._repos = repos
        self._model = model

    async def reply(
        self,
        project_id: UUID,
        *,
        message: str,
        diagram_xml: str,
        history: list[dict[str, str]],
    ) -> str:
        project = await get_project(self._repos, project_id)
        source_items = await self._repos.sources.list_by_project(project_id)
        question_items = await self._repos.questions.list_by_project(
            project_id, status=QuestionStatus.OPEN
        )
        sources: list[dict[str, str]] = []
        budget = 24_000
        for source in source_items:
            if not source.active or source.status is not SourceStatus.READY or budget <= 0:
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
        )

    async def reply_local(
        self,
        *,
        project_title: str,
        source: str,
        diagram_xml: str,
        history: list[dict[str, str]],
        message: str,
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
    ) -> str:
        return await self._model.chat(
            project_title=project_title,
            project_description=project_description,
            sources=sources,
            questions=questions,
            diagram_xml=diagram_xml,
            history=history,
            message=message,
        )
