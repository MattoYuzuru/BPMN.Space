"""Помощники тестов LLM: пайплайн на записанных ответах и HTTP-транспорт без сети."""

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx

from app.llm.client import ModelInfo
from app.llm.pipeline import LlmPipeline


class ScriptedClient:
    """`LlmClient`, отвечающий функцией `(system, user) -> текст` (синхронной или нет)."""

    def __init__(self, complete: Callable[[str, str], Any] | None = None) -> None:
        self._complete = complete
        # Параметры каждого вызова: тесты профиля проверяют effort и `max_tokens`.
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool,
        max_tokens: int,
        effort: str | None = None,
    ) -> str:
        self.calls.append({"json_mode": json_mode, "max_tokens": max_tokens, "effort": effort})
        if self._complete is None:
            raise RuntimeError("Ответ модели не задан")
        result = self._complete(system, user)
        if asyncio.iscoroutine(result):
            result = await result
        return result

    async def list_models(self) -> list[ModelInfo]:
        return [ModelInfo(id="scripted", label="scripted")]

    async def aclose(self) -> None:
        return None


class ScriptedPipeline(LlmPipeline):
    def __init__(
        self,
        *,
        api_key: str = "recorded-only",
        complete: Callable[[str, str], Any] | None = None,
        provider: str = "mock",  # mock: тесты подставляют свой `pace`
        model: str = "deepseek-chat",
        **options: Any,
    ) -> None:
        super().__init__(ScriptedClient(complete), provider=provider, model=model, **options)


def json_transport(
    handler: Callable[[httpx.Request], httpx.Response], requests: list[httpx.Request] | None = None
) -> httpx.MockTransport:
    def route(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        return handler(request)

    return httpx.MockTransport(route)


def ok_chat(content: str = "ok", **extra: Any) -> httpx.Response:
    return httpx.Response(
        200,
        content=json.dumps({"choices": [{"message": {"content": content}, **extra}], "usage": {}}),
    )


async def no_sleep(_seconds: float) -> None:
    return None
