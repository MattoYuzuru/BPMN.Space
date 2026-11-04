"""Персональные токены доступа для агентов (RFC-0007): `/me/api-tokens`.

Управлять токенами можно только из cookie-сессии: маршруты не объявляют право токена, поэтому
запрос с `Authorization: Bearer` получает `403` (см. `app.api.access.require_scope`).
"""

from uuid import UUID

from fastapi import APIRouter, Request, Response, status

from app.api.access import ensure_project_access
from app.api.auth import OptionalUserDep
from app.api.deps import ContainerDep
from app.api.schemas.api_tokens import ApiToken, ApiTokenCreate, ApiTokenCreated, ApiTokenList
from app.api.schemas.common import errors
from app.services.auth import UserRow
from app.services.errors import GoneError, NotFoundError, UnauthorizedError

router = APIRouter(tags=["api-tokens"])


def _account(user: UserRow | None) -> UUID:
    if user is None:
        raise UnauthorizedError("Войдите в аккаунт")
    return user.id


@router.get("/me/api-tokens", responses=errors(401, 403, 503))
async def list_api_tokens(container: ContainerDep, user: OptionalUserDep) -> ApiTokenList:
    """Неотозванные токены пользователя (и истёкшие), новые первыми; секретов в списке нет."""
    items = await container.api_tokens.list_for(_account(user))
    now = container.api_tokens.now()
    return ApiTokenList(items=[ApiToken.of(item, now) for item in items])


@router.post(
    "/me/api-tokens",
    status_code=status.HTTP_201_CREATED,
    responses=errors(401, 403, 404, 409, 422, 503),
)
async def create_api_token(
    body: ApiTokenCreate, request: Request, container: ContainerDep, user: OptionalUserDep
) -> ApiTokenCreated:
    """Выпустить токен. Ответ содержит секрет `bps_…` — единственный раз.

    Проекты из `project_ids` должны быть доступны пользователю (любая роль), иначе `404`.
    """
    user_id = _account(user)

    async def can_access(project_id: UUID) -> bool:
        try:
            await ensure_project_access(request, container, project_id, user, write=False)
        except (NotFoundError, GoneError):
            return False
        return True

    token, secret = await container.api_tokens.create(
        user_id,
        name=body.name,
        scopes=body.scopes,
        project_ids=body.project_ids,
        expires_in_days=body.expires_in_days,
        can_access=can_access,
    )
    shown = ApiToken.of(token, container.api_tokens.now())
    return ApiTokenCreated(**shown.model_dump(), secret=secret)


@router.delete(
    "/me/api-tokens/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=errors(401, 403, 404, 422),
)
async def revoke_api_token(
    token_id: UUID, container: ContainerDep, user: OptionalUserDep
) -> Response:
    """Отозвать токен: следующий запрос с ним получит `401`."""
    await container.api_tokens.revoke(_account(user), token_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
