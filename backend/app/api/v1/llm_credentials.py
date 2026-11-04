"""Ключи моделей пользователя (ADR-0011): `/me/llm-credentials`."""

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.api.auth import OptionalUserDep
from app.api.deps import ContainerDep
from app.api.ratelimit import limit_expensive
from app.api.schemas.common import errors
from app.api.schemas.llm_credentials import (
    LlmCredential,
    LlmCredentialCreate,
    LlmCredentialList,
    LlmCredentialUpdate,
    LlmModel,
    LlmModelList,
)
from app.services.auth import UserRow
from app.services.errors import UnauthorizedError

router = APIRouter(tags=["llm-credentials"])


def _account(user: UserRow | None) -> UUID:
    if user is None:
        raise UnauthorizedError("Войдите в аккаунт")
    return user.id


@router.get("/me/llm-credentials", responses=errors(401))
async def list_llm_credentials(container: ContainerDep, user: OptionalUserDep) -> LlmCredentialList:
    items = await container.llm_credentials.list_for(_account(user))
    return LlmCredentialList(
        items=[LlmCredential.of(item) for item in items],
        storage_available=container.llm_credentials.storage_available,
    )


@router.post(
    "/me/llm-credentials",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_expensive)],
    responses=errors(401, 409, 422, 429, 503),
)
async def create_llm_credential(
    body: LlmCredentialCreate, container: ContainerDep, user: OptionalUserDep
) -> LlmCredential:
    """Проверяет ключ запросом списка моделей у провайдера и сохраняет его зашифрованным."""
    created = await container.llm_credentials.create(
        _account(user),
        provider=body.provider,
        label=body.label,
        api_key=body.api_key,
        base_url=body.base_url,
        default_model=body.default_model,
        make_default=body.is_default,
    )
    return LlmCredential.of(created)


@router.patch("/me/llm-credentials/{credential_id}", responses=errors(401, 404, 422))
async def update_llm_credential(
    credential_id: UUID,
    body: LlmCredentialUpdate,
    container: ContainerDep,
    user: OptionalUserDep,
) -> LlmCredential:
    updated = await container.llm_credentials.update(
        _account(user),
        credential_id,
        label=body.label,
        default_model=body.default_model,
        is_default=body.is_default,
    )
    return LlmCredential.of(updated)


@router.delete(
    "/me/llm-credentials/{credential_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=errors(401, 404, 422),
)
async def delete_llm_credential(
    credential_id: UUID, container: ContainerDep, user: OptionalUserDep
) -> Response:
    await container.llm_credentials.delete(_account(user), credential_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/me/llm-credentials/{credential_id}/models",
    dependencies=[Depends(limit_expensive)],
    responses=errors(401, 404, 422, 429),
)
async def list_llm_models(
    credential_id: UUID, container: ContainerDep, user: OptionalUserDep
) -> LlmModelList:
    models = await container.llm_credentials.models(_account(user), credential_id)
    return LlmModelList(items=[LlmModel(id=item.id, label=item.label) for item in models])
