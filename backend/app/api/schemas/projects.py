"""Схемы проектов, примеров и расшифровки голоса."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.api.schemas.questions import Question
from app.api.schemas.runs import QuestionsSummary, Run
from app.api.schemas.sources import Source
from app.api.schemas.versions import Version
from app.domain.access import ProjectRole
from app.domain.models import ProjectStatus
from app.services import projects as svc


class ProjectCounts(ApiModel):
    sources: int = Field(description="Источники без ответов на вопросы")
    questions_open: int
    questions_resolved: int
    versions: int


class Project(ApiModel):
    id: UUID
    title: str
    description: str | None = None
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime
    counts: ProjectCounts
    lanes: list[str] = Field(description="Дорожки последней версии схемы — для карточки списка")
    access: ProjectRole = Field(
        description="Роль текущего пользователя: owner и editor меняют проект, viewer только читает"
    )

    @classmethod
    def of(cls, view: svc.ProjectView, access: ProjectRole) -> "Project":
        p = view.project
        return cls(
            id=p.id,
            title=p.title,
            description=p.description,
            status=view.status,
            created_at=p.created_at,
            updated_at=p.updated_at,
            counts=ProjectCounts.model_validate(view.counts),
            lanes=view.lanes,
            access=access,
        )


class ProjectPage(ApiModel):
    items: list[Project]
    next_cursor: str | None = Field(description="Курсор следующей страницы; null — конец")
    total: int = Field(description="Всего проектов с учётом поиска")


class ProjectDetail(Project):
    sources: list[Source]
    questions: list[Question]
    latest_version: Version | None = Field(description="Последняя версия без XML")
    active_run: Run | None
    summary: QuestionsSummary

    @classmethod
    def of_detail(cls, detail: svc.ProjectDetail, access: ProjectRole) -> "ProjectDetail":
        base = Project.of(detail.view, access)
        return cls(
            **base.model_dump(),
            sources=[Source.model_validate(s) for s in detail.sources],
            questions=[Question.model_validate(q) for q in detail.questions],
            latest_version=(
                Version.model_validate(detail.latest_version) if detail.latest_version else None
            ),
            active_run=Run.of(detail.active_run) if detail.active_run else None,
            summary=QuestionsSummary.model_validate(detail.summary),
        )


class ProjectCreate(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class ProjectFromExample(ApiModel):
    example_id: str = Field(description="id из `GET /examples`")


class ProjectUpdate(ApiModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class Example(ApiModel):
    id: str
    title: str
    description: str
    content: str = Field(description="Текст регламента — станет первым источником проекта")


class Transcription(ApiModel):
    text: str
    duration_sec: float
    language: str = Field(description="Код языка, например `ru-RU`")
