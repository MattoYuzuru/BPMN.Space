"""Единый формат ошибок: `{"detail": "<сообщение на русском>"}`."""

from collections.abc import Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.services.errors import (
    ConflictError,
    ForbiddenError,
    GoneError,
    InvalidInputError,
    NotFoundError,
    PayloadTooLargeError,
    ServiceError,
    StaleVersionError,
    UnauthorizedError,
    UnavailableError,
    UnsupportedMediaError,
)

_STATUS: dict[type[ServiceError], int] = {
    UnauthorizedError: 401,
    ForbiddenError: 403,
    NotFoundError: 404,
    GoneError: 410,
    UnavailableError: 503,
    ConflictError: 409,
    PayloadTooLargeError: 413,
    UnsupportedMediaError: 415,
    InvalidInputError: 422,
}

_HTTP_MESSAGES = {
    404: "Не найдено",
    405: "Метод не поддерживается",
}

_VALIDATION_MESSAGES = {
    "missing": "обязательное поле",
    "string_too_short": "слишком короткое значение",
    "string_too_long": "слишком длинное значение",
    "uuid_parsing": "некорректный идентификатор",
    "enum": "недопустимое значение",
    "literal_error": "недопустимое значение",
    "json_invalid": "некорректный JSON",
    "greater_than_equal": "значение меньше допустимого",
    "less_than_equal": "значение больше допустимого",
    "int_parsing": "ожидается целое число",
    "float_parsing": "ожидается число",
    "bool_parsing": "ожидается true или false",
    "string_type": "ожидается строка",
    "model_attributes_type": "ожидается объект",
}


def validation_message(errors: Sequence[Any]) -> str:
    if not errors:
        return "Некорректный запрос"
    first = errors[0]
    location = [str(part) for part in first.get("loc", ()) if part not in {"body", "query", "path"}]
    reason = _VALIDATION_MESSAGES.get(first.get("type", ""), "некорректное значение")
    if location:
        return f"Некорректный запрос: «{'.'.join(location)}» — {reason}"
    return f"Некорректный запрос: {reason}"


def install_error_handlers(app: FastAPI) -> None:
    async def service_error(_: Request, error: Exception) -> JSONResponse:
        assert isinstance(error, ServiceError)  # noqa: S101 — регистрируется только для ServiceError
        status = next((code for cls, code in _STATUS.items() if isinstance(error, cls)), 400)
        if isinstance(error, StaleVersionError):
            return JSONResponse(
                {
                    "detail": error.message,
                    "code": "stale_version",
                    "head_version_id": str(error.head_version_id)
                    if error.head_version_id
                    else None,
                    "head_version_number": error.head_version_number,
                },
                status_code=status,
            )
        return JSONResponse({"detail": error.message}, status_code=status)

    async def request_validation(_: Request, error: Exception) -> JSONResponse:
        assert isinstance(error, RequestValidationError)  # noqa: S101
        return JSONResponse({"detail": validation_message(error.errors())}, status_code=422)

    async def http_error(_: Request, error: Exception) -> JSONResponse:
        assert isinstance(error, StarletteHTTPException)  # noqa: S101
        detail = error.detail if isinstance(error.detail, str) else None
        message = _HTTP_MESSAGES.get(error.status_code) or detail or "Ошибка запроса"
        return JSONResponse(
            {"detail": message}, status_code=error.status_code, headers=error.headers
        )

    app.add_exception_handler(ServiceError, service_error)
    app.add_exception_handler(RequestValidationError, request_validation)
    app.add_exception_handler(StarletteHTTPException, http_error)
