"""Каталог провайдеров для раздела «Инструменты» (RFC-0006, шаг 6).

Дополняет `GET /me/credentials`: там — что уже подключено, здесь — чем возможность можно закрыть
и где взять ключ. Как и управление ключами, маршрут доступен только по cookie-сессии: право
токена доступа (RFC-0007) не объявлено, поэтому `Authorization: Bearer` не подходит.
"""

from fastapi import APIRouter

from app.api.auth import OptionalUserDep
from app.api.deps import ContainerDep
from app.api.schemas.common import errors
from app.api.schemas.tool_catalog import ToolCatalogResponse
from app.services.errors import UnauthorizedError

router = APIRouter(tags=["tools"])


@router.get("/me/tool-catalog", responses=errors(401))
async def tool_catalog(container: ContainerDep, user: OptionalUserDep) -> ToolCatalogResponse:
    """Возможности, провайдеры, где взять ключ и что закрывает модель (данные на 04.11.2026)."""
    if user is None:
        raise UnauthorizedError("Войдите в аккаунт")
    return ToolCatalogResponse.of(container.tool_catalog.catalog())


__all__ = ["router"]
