"""Ключи пользователя по типам задач (RFC-0006): `/me/credentials`.

Только cookie-сессия: маршруты не объявляют право токена доступа (RFC-0007), поэтому по
`Authorization: Bearer` они закрыты — управлять ключами можно лишь из браузера под своим
аккаунтом. Открытый ключ принимается один раз и ни в одном ответе не возвращается.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.api.auth import OptionalUserDep
from app.api.deps import ContainerDep
from app.api.ratelimit import limit_expensive
from app.api.schemas.common import errors
from app.api.schemas.credentials import (
    CapabilityCardSchema,
    Credential,
    CredentialCheckResult,
    CredentialCreate,
    CredentialList,
    CredentialUpdate,
    monthly_limit_dict,
)
from app.domain.capabilities import CredentialKind
from app.services.auth import UserRow
from app.services.errors import UnauthorizedError

router = APIRouter(tags=["credentials"])


def _account(user: UserRow | None) -> UUID:
    if user is None:
        raise UnauthorizedError("Войдите в аккаунт")
    return user.id


@router.get("/me/credentials", responses=errors(401))
async def list_credentials(container: ContainerDep, user: OptionalUserDep) -> CredentialList:
    """Все ключи пользователя, карточки возможностей и признак доступности хранилища."""
    user_id = _account(user)
    items = await container.credentials.list_for(user_id)
    cards = await container.credentials.capabilities(user_id)
    return CredentialList(
        items=[Credential.of(item) for item in items],
        storage_available=container.credentials.storage_available,
        capabilities=[CapabilityCardSchema.of(card) for card in cards],
    )


@router.post(
    "/me/credentials",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_expensive)],
    responses=errors(401, 409, 422, 429, 503),
)
async def create_credential(
    body: CredentialCreate, container: ContainerDep, user: OptionalUserDep
) -> Credential:
    """Проверяет ключ дешёвым запросом провайдера и сохраняет его зашифрованным.

    Один ключ может закрывать несколько возможностей: OpenAI — модели и распознавание речи.
    """
    created = await container.credentials.create(
        _account(user),
        kinds=tuple(CredentialKind(kind) for kind in body.kinds),
        provider=body.provider,
        label=body.label,
        api_key=body.api_key,
        base_url=body.base_url,
        default_model=body.default_model,
        priority=body.priority,
        enabled=body.enabled,
        monthly_limit=monthly_limit_dict(body.monthly_limit),
        make_default=body.is_default,
    )
    return Credential.of(created)


@router.patch("/me/credentials/{credential_id}", responses=errors(401, 404, 422))
async def update_credential(
    credential_id: UUID,
    body: CredentialUpdate,
    container: ContainerDep,
    user: OptionalUserDep,
) -> Credential:
    """Название, модель, приоритет, включённость и лимит; ключ и адрес не меняются."""
    updated = await container.credentials.update(
        _account(user),
        credential_id,
        label=body.label,
        default_model=body.default_model,
        is_default=body.is_default,
        priority=body.priority,
        enabled=body.enabled,
        monthly_limit=monthly_limit_dict(body.monthly_limit),
        clear_monthly_limit=body.clear_monthly_limit,
    )
    return Credential.of(updated)


@router.delete(
    "/me/credentials/{credential_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=errors(401, 404, 422),
)
async def delete_credential(
    credential_id: UUID, container: ContainerDep, user: OptionalUserDep
) -> Response:
    await container.credentials.delete(_account(user), credential_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/me/credentials/{credential_id}/check",
    dependencies=[Depends(limit_expensive)],
    responses=errors(401, 404, 422, 429, 503),
)
async def check_credential(
    credential_id: UUID, container: ContainerDep, user: OptionalUserDep
) -> CredentialCheckResult:
    """Проверка ключа для каждого типа: отказ провайдера — `ok=false` с понятной причиной.

    Успешная проверка снимает отметку ошибки и снова включает ключ, отключённый после отказа
    провайдера. Для возможностей волны 3 проверка честно отвечает, что пока недоступна.
    """
    result = await container.credentials.check(_account(user), credential_id)
    return CredentialCheckResult.of(result)
