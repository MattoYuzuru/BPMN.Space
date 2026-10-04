"""Ограничение размера тела запроса до того, как оно попадёт в память или на диск.

Multipart-парсер Starlette складывает загрузку во временный файл ещё до вызова обработчика,
поэтому проверка внутри роута опоздала бы. Здесь: ранний ответ `413` по `Content-Length` и
счётчик принятых байт для запросов без него (chunked). Точные лимиты по смыслу (размер файла,
схемы, аудио) дополнительно проверяют сервисы.
"""

import re
from collections.abc import MutableMapping
from dataclasses import dataclass
from typing import Any

from fastapi import UploadFile
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import Settings
from app.services.common import too_large

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_MULTIPART_OVERHEAD = 1024 * 1024  # границы частей, имя файла, поле title
_JSON_OVERHEAD = 64 * 1024
_CHUNK = 1024 * 1024


@dataclass(frozen=True, slots=True)
class BodyRule:
    pattern: re.Pattern[str]
    limit: int
    message: str


def build_rules(settings: Settings) -> tuple[list[BodyRule], BodyRule]:
    """Правила по путям и общее правило для всех остальных запросов с телом."""
    prefix = re.escape(settings.api_prefix)
    specific = [
        BodyRule(
            re.compile(rf"^{prefix}/projects/[^/]+/sources/file$"),
            settings.max_upload_bytes + _MULTIPART_OVERHEAD,
            too_large("Файл", settings.max_upload_bytes).message,
        ),
        BodyRule(
            re.compile(rf"^{prefix}/transcriptions$"),
            settings.max_audio_bytes + _MULTIPART_OVERHEAD,
            too_large("Запись", settings.max_audio_bytes).message,
        ),
        BodyRule(
            re.compile(rf"^{prefix}/projects/[^/]+/diagram$"),
            # JSON экранирует кавычки и переводы строк: запас вдвое.
            settings.max_diagram_bytes * 2 + _JSON_OVERHEAD,
            too_large("Схема", settings.max_diagram_bytes).message,
        ),
    ]
    # Текст источника — до `max_text_chars` символов (до 4 байт каждый в UTF-8).
    default_limit = max(settings.max_text_chars * 4, settings.max_diagram_bytes * 2)
    default = BodyRule(re.compile(r".*"), default_limit + _JSON_OVERHEAD, "Запрос слишком большой")
    return specific, default


class BodyLimitMiddleware:
    """ASGI-middleware: `413 {"detail": …}` для слишком больших тел запроса."""

    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        self._app = app
        self._rules, self._default = build_rules(settings)

    def _rule(self, path: str) -> BodyRule:
        return next((rule for rule in self._rules if rule.pattern.match(path)), self._default)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in _SAFE_METHODS:
            await self._app(scope, receive, send)
            return
        rule = self._rule(scope["path"])
        too_big = JSONResponse({"detail": rule.message}, status_code=413)
        declared = _content_length(scope)
        if declared is not None and declared > rule.limit:
            await too_big(scope, receive, send)
            return
        received = 0
        exceeded = False
        started = False

        async def counting_receive() -> Message:
            nonlocal received, exceeded
            if exceeded:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > rule.limit:
                    # FastAPI превращает любое исключение чтения тела в 400, поэтому 413
                    # отправляем сами, а приложению сообщаем об обрыве соединения.
                    exceeded = True
                    if not started:
                        await too_big(scope, receive, send)
                    return {"type": "http.disconnect"}
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if exceeded:
                return  # 413 уже отправлен, ответ приложения (400 об обрыве) не нужен
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self._app(scope, counting_receive, tracking_send)
        except Exception:
            if not exceeded:
                raise


def _content_length(scope: MutableMapping[str, Any]) -> int | None:
    for name, value in scope["headers"]:
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


async def read_upload(
    file: UploadFile,
    *,
    subject: str,
    limit: int,
) -> bytes:
    """Читает загрузку кусками и обрывает (`413`), как только набралось больше `limit` байт."""
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(_CHUNK):
        total += len(chunk)
        if total > limit:
            raise too_large(subject, limit)
        chunks.append(chunk)
    return b"".join(chunks)


__all__ = ["BodyLimitMiddleware", "read_upload"]
