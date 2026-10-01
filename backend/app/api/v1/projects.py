"""Проекты и примеры."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.api.deps import ContainerDep
from app.api.schemas.common import errors
from app.api.schemas.projects import (
    Example,
    Project,
    ProjectCreate,
    ProjectDetail,
    ProjectFromExample,
    ProjectPage,
    ProjectUpdate,
)

router = APIRouter(tags=["projects"])


@router.get("/projects", responses=errors(422))
async def list_projects(
    container: ContainerDep,
    cursor: Annotated[str | None, Query(description="`next_cursor` прошлой страницы")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    q: Annotated[str | None, Query(max_length=200, description="Поиск по названию")] = None,
) -> ProjectPage:
    """Проекты: сначала недавно изменённые. Курсорная пагинация."""
    page = await container.projects.list(cursor=cursor, limit=limit, query=q)
    return ProjectPage(
        items=[Project.of(view) for view in page.items],
        next_cursor=page.next_cursor,
        total=page.total,
    )


@router.post("/projects", status_code=status.HTTP_201_CREATED, responses=errors(422))
async def create_project(body: ProjectCreate, container: ContainerDep) -> Project:
    view = await container.projects.create(title=body.title, description=body.description)
    return Project.of(view)


@router.post(
    "/projects/from-example", status_code=status.HTTP_201_CREATED, responses=errors(404, 422)
)
async def create_project_from_example(body: ProjectFromExample, container: ContainerDep) -> Project:
    """Проект с текстом примера в качестве первого источника."""
    return Project.of(await container.projects.create_from_example(body.example_id))


@router.get("/projects/{project_id}", responses=errors(404, 422))
async def get_project(project_id: UUID, container: ContainerDep) -> ProjectDetail:
    """Проект целиком: источники, вопросы, последняя версия (без XML), активный прогон."""
    return ProjectDetail.of_detail(await container.projects.detail(project_id))


@router.patch("/projects/{project_id}", responses=errors(404, 422))
async def update_project(project_id: UUID, body: ProjectUpdate, container: ContainerDep) -> Project:
    view = await container.projects.update(
        project_id, title=body.title, description=body.description, fields=body.model_fields_set
    )
    return Project.of(view)


@router.delete(
    "/projects/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=errors(404, 409, 422),
)
async def delete_project(project_id: UUID, container: ContainerDep) -> Response:
    await container.projects.delete(project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/examples", tags=["examples"])
async def list_examples(container: ContainerDep) -> list[Example]:
    """Демо-примеры процессов для быстрого старта."""
    return [Example.model_validate(item) for item in container.examples.list()]
