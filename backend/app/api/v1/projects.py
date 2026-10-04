"""Проекты и примеры."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response, status

from app.api.access import ProjectRole, ensure_project_access, project_roles, require_account
from app.api.auth import OptionalUserDep
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
from app.domain.access import ProjectScope
from app.domain.onboarding import ChecklistItem
from app.services.errors import ForbiddenError

router = APIRouter(tags=["projects"])


@router.get("/projects", responses=errors(401, 422))
async def list_projects(  # noqa: PLR0917 - FastAPI binds each query parameter independently
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
    cursor: Annotated[str | None, Query(description="`next_cursor` прошлой страницы")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    q: Annotated[str | None, Query(max_length=200, description="Поиск по названию")] = None,
    scope: Annotated[
        ProjectScope,
        Query(
            description=(
                "Что показывать: `all` — всё доступное (по умолчанию), `own` — свои, "
                "`shared` — где вы редактор по приглашению, `examples` — демо-примеры. "
                "Без аккаунтов параметр не действует."
            )
        ),
    ] = ProjectScope.ALL,
) -> ProjectPage:
    """Проекты: сначала недавно изменённые. Курсорная пагинация. Гостям — 401."""
    owner_id = require_account(request, user)
    page = await container.projects.list(
        cursor=cursor,
        limit=limit,
        query=q,
        owner_id=owner_id,
        scope_to_user=request.app.state.auth_enabled,
        scope=scope,
    )
    roles = await project_roles(request, container, [view.project.id for view in page.items], user)
    return ProjectPage(
        items=[
            Project.of(view, roles.get(view.project.id, ProjectRole.VIEWER)) for view in page.items
        ],
        next_cursor=page.next_cursor,
        total=page.total,
    )


@router.post("/projects", status_code=status.HTTP_201_CREATED, responses=errors(401, 422))
async def create_project(
    body: ProjectCreate,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> Project:
    owner_id = require_account(request, user)
    view = await container.projects.create(
        title=body.title, description=body.description, owner_id=owner_id
    )
    await container.onboarding.record(owner_id, ChecklistItem.PROJECT_CREATED)
    return Project.of(view, ProjectRole.OWNER)


@router.post(
    "/projects/from-example", status_code=status.HTTP_201_CREATED, responses=errors(401, 404, 422)
)
async def create_project_from_example(
    body: ProjectFromExample,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> Project:
    """Проект с текстом примера в качестве первого источника."""
    owner_id = require_account(request, user)
    view = await container.projects.create_from_example(body.example_id, owner_id=owner_id)
    await container.onboarding.record(owner_id, ChecklistItem.PROJECT_CREATED)
    return Project.of(view, ProjectRole.OWNER)


@router.get("/projects/{project_id}", responses=errors(401, 404, 422))
async def get_project(
    project_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> ProjectDetail:
    """Проект целиком: источники, вопросы, последняя версия (без XML), активный прогон."""
    role = await ensure_project_access(request, container, project_id, user, write=False)
    return ProjectDetail.of_detail(await container.projects.detail(project_id), role)


@router.patch("/projects/{project_id}", responses=errors(401, 403, 404, 422))
async def update_project(
    project_id: UUID,
    body: ProjectUpdate,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> Project:
    role = await ensure_project_access(request, container, project_id, user, write=True)
    view = await container.projects.update(
        project_id, title=body.title, description=body.description, fields=body.model_fields_set
    )
    return Project.of(view, role)


@router.delete(
    "/projects/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=errors(401, 403, 404, 409, 422),
)
async def delete_project(
    project_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> Response:
    role = await ensure_project_access(request, container, project_id, user, write=True)
    if role is not ProjectRole.OWNER:
        raise ForbiddenError("Удалить проект может только владелец")
    await container.projects.delete(project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/examples", tags=["examples"])
async def list_examples(container: ContainerDep) -> list[Example]:
    """Демо-примеры процессов для быстрого старта."""
    return [Example.model_validate(item) for item in container.examples.list()]
