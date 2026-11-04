"""Участники проекта и ссылки доступа: управление (владелец) и открытие по ссылке."""

from uuid import UUID

from fastapi import APIRouter, Request, Response, status

from app.api.access import ProjectRole, ensure_project_access, get_active_share_link
from app.api.auth import OptionalUserDep
from app.api.deps import ContainerDep
from app.api.responses import bpmn_attachment
from app.api.schemas.common import errors
from app.api.schemas.projects import ProjectDetail as ProjectDetailSchema
from app.api.schemas.questions import Question
from app.api.schemas.sharing import (
    AgentPrompt,
    AgentTokenIssued,
    ProjectMemberRead,
    ReviewQuestionRecap,
    ReviewScope,
    ShareAccepted,
    SharedProject,
    ShareLinkCreate,
    ShareLinkCreated,
    ShareLinkRead,
    ShareRole,
)
from app.container import Container
from app.domain.onboarding import ChecklistItem
from app.services.auth import UserRow
from app.services.errors import ForbiddenError, NotFoundError, UnauthorizedError

router = APIRouter(tags=["sharing"])


async def _ensure_owner(
    request: Request, container: Container, project_id: UUID, user: UserRow | None, message: str
) -> None:
    role = await ensure_project_access(request, container, project_id, user, write=False)
    if role is not ProjectRole.OWNER:
        raise ForbiddenError(message)


@router.get(
    "/projects/{project_id}/members",
    response_model=list[ProjectMemberRead],
    responses=errors(401, 403, 404, 410, 422),
)
async def list_project_members(
    project_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> list[ProjectMemberRead]:
    await _ensure_owner(
        request, container, project_id, user, "Состав участников видит только владелец"
    )
    return [
        ProjectMemberRead(
            user_id=member.user_id,
            email=member.email,
            role=ShareRole(member.role),
            added_at=member.added_at,
        )
        for member in await container.sharing.list_members(project_id)
    ]


@router.delete(
    "/projects/{project_id}/members/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=errors(401, 403, 404, 410, 422),
)
async def remove_project_member(
    project_id: UUID,
    member_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> Response:
    await _ensure_owner(
        request, container, project_id, user, "Участников может удалять только владелец"
    )
    await container.sharing.remove_member(project_id, member_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/projects/{project_id}/membership",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=errors(401, 403, 404, 410, 422),
)
async def leave_project(
    project_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> Response:
    """Выйти из общего проекта; данные владельца и остальных участников сохраняются."""
    await ensure_project_access(request, container, project_id, user, write=False)
    if user is None:
        raise UnauthorizedError("Войдите в аккаунт")
    await container.sharing.leave_project(project_id, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/projects/{project_id}/share-links",
    status_code=status.HTTP_201_CREATED,
    response_model=ShareLinkCreated,
    responses=errors(401, 403, 404, 410, 422),
)
async def create_share_link(
    project_id: UUID,
    body: ShareLinkCreate,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> ShareLinkCreated:
    """Создать ссылку на чтение либо приглашение редактора; сырой токен выдаётся один раз.

    У обеих ролей одинаковый срок: 7, 30, 365 дней или бессрочно (0); по умолчанию 30 дней.
    """
    await _ensure_owner(
        request, container, project_id, user, "Ссылки доступа может создавать только владелец"
    )
    if user is None:  # без аккаунтов владельца нет, ссылки недоступны
        raise UnauthorizedError("Войдите в аккаунт")
    lane_ids: tuple[str, ...] = ()
    if body.role is ShareRole.REVIEWER and body.lane_ids:
        lane_ids = await container.review.validate_lane_ids(project_id, body.lane_ids)
    created = await container.sharing.create_link(
        project_id,
        role=body.role.value,
        expires_in_days=body.expires_in_days,
        created_by=user.id,
        lane_ids=lane_ids,
    )
    await container.onboarding.record(user.id, ChecklistItem.PROJECT_SHARED)
    return ShareLinkCreated(
        id=created.link.id,
        role=body.role,
        url_path=f"/share/{created.token}",
        created_at=created.link.created_at,
        expires_at=created.link.expires_at,
        lane_ids=list(created.link.lane_ids),
    )


@router.get(
    "/projects/{project_id}/share-links",
    response_model=list[ShareLinkRead],
    responses=errors(401, 403, 404, 410, 422),
)
async def list_share_links(
    project_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> list[ShareLinkRead]:
    await _ensure_owner(request, container, project_id, user, "Списком ссылок управляет владелец")
    return [
        ShareLinkRead(
            id=link.id,
            role=ShareRole(link.role),
            created_at=link.created_at,
            expires_at=link.expires_at,
            revoked_at=link.revoked_at,
            lane_ids=list(link.lane_ids),
        )
        for link in await container.sharing.list_links(project_id)
    ]


@router.delete(
    "/projects/{project_id}/share-links/{link_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=errors(401, 403, 404, 410, 422),
)
async def revoke_share_link(
    project_id: UUID,
    link_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> Response:
    await _ensure_owner(request, container, project_id, user, "Ссылками доступа управляет владелец")
    await container.sharing.revoke_link(project_id, link_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/shares/{token}", response_model=SharedProject, responses=errors(401, 404, 410, 422))
async def read_shared_project(
    token: str,
    container: ContainerDep,
    user: OptionalUserDep,
) -> SharedProject:
    """Открыть проект по ссылке. Ссылка на чтение и проверку работает без входа (гостям тоже).

    У ссылки проверки (reviewer) вопросы и счётчики сужены до области-дорожек: остальное —
    чтение схемы и оснований; менять проект такая ссылка не даёт.
    """
    link = await get_active_share_link(container, token)
    role = ShareRole(link.role)
    if role is ShareRole.EDITOR and user is None:
        raise UnauthorizedError("Войдите или зарегистрируйтесь, чтобы открыть проект редактором")
    detail = await container.projects.detail(link.project_id)
    if role is ShareRole.REVIEWER:
        detail = await container.review.filter_detail(link.project_id, detail, link.lane_ids)
        project_role = ProjectRole.REVIEWER
    else:
        project_role = ProjectRole.EDITOR if role is ShareRole.EDITOR else ProjectRole.VIEWER
    lane_names = await container.review.lane_names(link.project_id, link.lane_ids)
    return SharedProject(
        role=role,
        editor_requires_account=role is ShareRole.EDITOR,
        scope=ReviewScope(
            lane_ids=list(link.lane_ids),
            lanes=list(lane_names),
            whole_project=not link.lane_ids,
        ),
        detail=ProjectDetailSchema.of_detail(detail, project_role),
    )


@router.get(
    "/shares/{token}/versions/{version_id}/xml",
    response_class=Response,
    responses={
        200: {
            "content": {"application/xml": {}},
            "description": "Диаграмма BPMN по ссылке доступа (вложением)",
        },
        **errors(401, 404, 410, 422),
    },
)
async def download_shared_diagram(
    token: str,
    version_id: UUID,
    container: ContainerDep,
    user: OptionalUserDep,
) -> Response:
    link = await get_active_share_link(container, token)
    if link.role == ShareRole.EDITOR.value and user is None:
        raise UnauthorizedError("Войдите, чтобы открыть ссылку редактора")
    version = await container.versions.get(version_id)
    if version.project_id != link.project_id:
        raise NotFoundError("Версия не относится к этому проекту")
    return bpmn_attachment(version.xml, number=version.number)


@router.post(
    "/shares/{token}/accept",
    response_model=ShareAccepted,
    responses=errors(401, 404, 410, 422),
)
async def accept_share_link(
    token: str,
    container: ContainerDep,
    user: OptionalUserDep,
) -> ShareAccepted:
    link = await get_active_share_link(container, token)
    if ShareRole(link.role) is ShareRole.REVIEWER:
        raise ForbiddenError(
            "Ссылка проверки не добавляет проект в профиль: откройте её и подключите агента"
        )
    if user is None:
        raise UnauthorizedError("Войдите или зарегистрируйтесь, чтобы добавить проект в профиль")
    await container.sharing.accept_invite(link.project_id, user.id, link.role, link_id=link.id)
    return ShareAccepted(project_id=link.project_id, role=ShareRole(link.role))


@router.get(
    "/shares/{token}/questions",
    response_model=list[Question],
    responses=errors(401, 403, 404, 410, 422),
)
async def read_shared_questions(
    token: str,
    container: ContainerDep,
    user: OptionalUserDep,
) -> list[Question]:
    """Вопросы по ссылке: у проверки — только область-дорожки, у просмотра — все.

    Технические вопросы запуска проверяющему не показываются: они решаются действием.
    """
    link = await get_active_share_link(container, token)
    role = ShareRole(link.role)
    if role is ShareRole.EDITOR and user is None:
        raise UnauthorizedError("Войдите, чтобы открыть ссылку редактора")
    questions = await container.questions.list(link.project_id, status=None)
    if role is ShareRole.REVIEWER:
        questions = await container.review.filter_questions(
            link.project_id, questions, link.lane_ids
        )
    return [Question.model_validate(question) for question in questions]


@router.get(
    "/shares/{token}/agent-prompt",
    response_model=AgentPrompt,
    responses=errors(401, 404, 410, 422),
)
async def read_agent_prompt(
    token: str,
    container: ContainerDep,
    user: OptionalUserDep,
) -> AgentPrompt:
    """Готовый текст «проверь дорожку» для агента коллеги.

    Без секрета ссылки: промпт можно вставить в своего агента без аккаунта и без токена.
    """
    link = await get_active_share_link(container, token)
    role = ShareRole(link.role)
    if role is ShareRole.EDITOR and user is None:
        raise UnauthorizedError("Войдите, чтобы открыть ссылку редактора")
    prompt = await container.review.agent_prompt(link)
    return AgentPrompt(
        text=prompt.text,
        lane_ids=list(prompt.lane_ids),
        lanes=list(prompt.lane_names),
        questions_recap=[
            ReviewQuestionRecap.model_validate(item) for item in prompt.questions_recap
        ],
        whole_project=prompt.whole_project,
    )


@router.post(
    "/shares/{token}/agent-token",
    status_code=status.HTTP_201_CREATED,
    response_model=AgentTokenIssued,
    responses=errors(401, 403, 404, 409, 410, 422),
)
async def issue_agent_token(
    token: str,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> AgentTokenIssued:
    """Выпустить токен агента для вошедшего получателя ссылки проверки.

    Токен: права `projects:read` и `questions:answer`, только проект ссылки, срок — срок
    ссылки. Секрет показывается один раз. Отзыв или истечение ссылки закрывают токен
    мгновенно: ссылка проверяется при каждом запросе токена.
    """
    link = await get_active_share_link(container, token)
    if user is None:
        raise UnauthorizedError(
            "Войдите или зарегистрируйтесь, чтобы получить токен агента по ссылке проверки"
        )
    issued = await container.review.create_agent_token(link, user.id)
    base = str(request.base_url).rstrip("/")
    mcp_url = f"{base}/mcp"  # MCP-сервер бэкенда (RFC-0007); в Docker проксирует Caddy
    return AgentTokenIssued(
        token_id=issued.token.id,
        secret=issued.secret,
        name=issued.token.name,
        project_id=link.project_id,
        lane_ids=list(issued.token.lane_ids or ()),
        scopes=[scope.value for scope in issued.token.scopes],
        expires_at=issued.token.expires_at,
        mcp_url=mcp_url,
        command=(
            "claude mcp add --transport http bpmn-space "
            f'{mcp_url} --header "Authorization: Bearer {issued.secret}"'
        ),
    )
