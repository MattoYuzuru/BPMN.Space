"""Ошибки сценариев. API превращает их в HTTP-коды и `{"detail": "<сообщение>"}`.

Сообщения — для пользователя, на русском, без технических подробностей.
"""


class ServiceError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(ServiceError):
    """404: сущности нет."""


class ConflictError(ServiceError):
    """409: недопустимо в текущем состоянии (переход статуса, прогон уже идёт)."""


class InvalidInputError(ServiceError):
    """422: данные корректны по форме, но не по смыслу (пустой текст, битый XML)."""


class UnsupportedMediaError(ServiceError):
    """415: формат файла не поддерживается."""


class PayloadTooLargeError(ServiceError):
    """413: файл больше допустимого."""
