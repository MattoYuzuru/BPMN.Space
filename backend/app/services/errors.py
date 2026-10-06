"""Ошибки сценариев. API превращает их в HTTP-коды и `{"detail": "<сообщение>"}`.

Сообщения — для пользователя, на русском, без технических подробностей.
"""

from uuid import UUID


class ServiceError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(ServiceError):
    """404: сущности нет."""


class ConflictError(ServiceError):
    """409: недопустимо в текущем состоянии (переход статуса, прогон уже идёт)."""


class StaleVersionError(ConflictError):
    """409: сохранение начато от старой версии; сохраняет id текущей головы проекта."""

    def __init__(self, head_version_id: UUID | None, head_version_number: int | None) -> None:
        super().__init__("Схема уже изменена другим участником. Обновите её перед сохранением")
        self.head_version_id = head_version_id
        self.head_version_number = head_version_number


class InvalidInputError(ServiceError):
    """422: данные корректны по форме, но не по смыслу (пустой текст, битый XML)."""


class UnsupportedMediaError(ServiceError):
    """415: формат файла не поддерживается."""


class PayloadTooLargeError(ServiceError):
    """413: файл больше допустимого."""


class GoneError(ServiceError):
    """410: объект существовал, но больше недоступен (истёкшая ссылка)."""


class ForbiddenError(ServiceError):
    """403: роль пользователя не позволяет действие."""


class UnauthorizedError(ServiceError):
    """401: нужен вход в аккаунт."""


class UnavailableError(ServiceError):
    """503: нужная часть системы не подключена (например, нет PostgreSQL)."""
