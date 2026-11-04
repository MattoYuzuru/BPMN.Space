"""Проекты и примеры."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response, status

from app.api.access import (
    ApiScope,
    ProjectRole,
    ensure_project_access,
    is_review_token,
    project_roles,
    require_account,
    require_scope,
    review_lane_ids,
    token_project_ids,
)
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
from app.api.schemas.sharing import AgentActivity, AgentActivityEvent
from app.domain.access import ProjectScope
from app.domain.onboarding import ChecklistItem
from app.services.errors import ForbiddenError

router = APIRouter(tags=["projects"])


@router.get(
    "/projects", dependencies=[require_scope(ApiScope.PROJECTS_READ)], responses=errors(401, 422)
)
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
                "`shared` — принятые по ссылке проекты, `examples` — демо-примеры. "
                "Без аккаунтов параметр не действует."
            )
        ),
    ] = ProjectScope.ALL,
) -> ProjectPage:
    """Проекты: сначала недавно изменённые. Курсорная пагинация. Гостям — 401.

    Токен проверки не даёт членства: его проект виден отдельной карточкой с ролью reviewer,
    без общего списка чужих проектов владельца.
    """
    review = is_review_token(request)
    owner_id = None if review else require_account(request, user)
    page = await container.projects.list(
        cursor=cursor,
        limit=limit,
        query=q,
        owner_id=owner_id,
        scope_to_user=request.app.state.auth_enabled and not review,
        scope=scope,
        only_ids=token_project_ids(request),
    )
    roles = await project_roles(request, container, [view.project.id for view in page.items], user)
    return ProjectPage(
        items=[
            Project.of(view, roles.get(view.project.id, ProjectRole.VIEWER)) for view in page.items
        ],
        next_cursor=page.next_cursor,
        total=page.total,
    )


@router.post(
    "/projects",
    dependencies=[require_scope(ApiScope.PROJECTS_WRITE, all_projects=True)],
    status_code=status.HTTP_201_CREATED,
    responses=errors(401, 422),
)
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
    "/projects/from-example",
    dependencies=[require_scope(ApiScope.PROJECTS_WRITE, all_projects=True)],
    status_code=status.HTTP_201_CREATED,
    responses=errors(401, 404, 410, 422),
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


@router.get(
    "/projects/{project_id}",
    dependencies=[require_scope(ApiScope.PROJECTS_READ)],
    responses=errors(401, 404, 410, 422),
)
async def get_project(
    project_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> ProjectDetail:
    """Проект целиком: источники, вопросы, последняя версия (без XML), активный прогон.

    По токену проверки вопросы и счётчики сужены до области-дорожек ссылки (RFC-0007).
    """
    role = await ensure_project_access(request, container, project_id, user, write=False)
    detail = await container.projects.detail(project_id)
    lanes = review_lane_ids(request)
    if lanes is not None:
        detail = await container.review.filter_detail(project_id, detail, lanes)
    return ProjectDetail.of_detail(detail, role)


@router.get(
    "/projects/{project_id}/agent-activity",
    dependencies=[require_scope(ApiScope.PROJECTS_READ)],
    responses=errors(401, 403, 404, 410, 422),
)
async def project_agent_activity(
    project_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> AgentActivity:
    """Журнал активности агента в проекте (v1): добавленные материалы и ответы.

    Собирается из существующих данных (`sources.origin=agent`, `questions.answer.via=agent`),
    без отдельной таблицы событий. Доступен участникам проекта, но не по ссылке проверки.
    """
    role = await ensure_project_access(request, container, project_id, user, write=False)
    if role is ProjectRole.REVIEWER:
        raise ForbiddenError("Журнал активности агента доступен участникам проекта")
    events = await container.review.agent_activity(project_id)
    return AgentActivity(
        items=[
            AgentActivityEvent(
                kind=event.kind,
                at=event.at,
                token_name=event.token_name,
                title=event.title,
                detail=event.detail,
                share_link_id=event.share_link_id,
                source_id=event.source_id,
                question_id=event.question_id,
                question_code=event.question_code,
            )
            for event in events
        ],
        total=len(events),
    )


@router.patch(
    "/projects/{project_id}",
    dependencies=[require_scope(ApiScope.PROJECTS_WRITE)],
    responses=errors(401, 403, 404, 410, 422),
)
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
    responses=errors(401, 403, 404, 409, 410, 422),
)
async def delete_project(
    project_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> Response:
    """Владелец удаляет проект для всех; viewer/editor удаляет только своё членство."""
    role = await ensure_project_access(request, container, project_id, user, write=False)
    if role is ProjectRole.OWNER:
        await container.projects.delete(project_id)
    else:
        user_id = require_account(request, user)
        assert user_id is not None  # noqa: S101 — без auth роль всегда owner
        await container.sharing.leave_project(project_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/examples", tags=["examples"])
async def list_examples(container: ContainerDep) -> list[Example]:
    """Демо-примеры процессов для быстрого старта."""
    return [Example.model_validate(item) for item in container.examples.list()]
