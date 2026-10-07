"""Общие схемы контракта API v1. Поля — snake_case, id — UUID, даты — ISO 8601 (UTC)."""

from http import HTTPStatus
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ErrorResponse(ApiModel):
    detail: str = Field(description="Сообщение об ошибке для пользователя, на русском")


class GoneErrorResponse(ErrorResponse):
    code: Literal["PROJECT_DELETED"] | None = Field(
        default=None, description="PROJECT_DELETED — автор удалил ранее доступный проект"
    )


class TranscriptionErrorResponse(ErrorResponse):
    code: Literal["NO_SPEECH"] | None = Field(
        default=None, description="NO_SPEECH — запись обработана, но речь не распознана"
    )


class Quote(ApiModel):
    """Цитата из источника: доказательство, трассировка или повод для вопроса."""

    source_id: UUID
    quote: str = Field(description="Точный фрагмент текста источника")


def errors(*codes: int) -> dict[int | str, dict[str, object]]:
    """Описание ошибок для OpenAPI: все ошибки имеют вид `{"detail": "…"}`."""
    descriptions = {
        401: "Требуется вход в аккаунт",
        403: "Недостаточно прав для операции",
        404: "Не найдено",
        409: "Конфликт состояния",
        410: "Ссылка истекла либо автор удалил проект",
        413: "Слишком большой файл",
        415: "Формат не поддерживается",
        422: "Некорректные данные",
        429: "Слишком много запросов; повторите через `Retry-After` секунд",
        502: "Провайдер модели вернул ошибку",
        503: "Сервис или помощник не настроен",
    }
    return {
        code: {
            "model": GoneErrorResponse if code == HTTPStatus.GONE else ErrorResponse,
            "description": descriptions[code],
        }
        for code in codes
    }
