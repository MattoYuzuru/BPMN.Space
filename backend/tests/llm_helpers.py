"""Помощники тестов LLM: пайплайн на записанных ответах и HTTP-транспорт без сети."""

import asyncio
import json
from collections.abc import Callable, Sequence
from typing import Any

import httpx

from app.llm.base import record_usage
from app.llm.client import ModelInfo
from app.llm.pipeline import LlmPipeline
from app.llm.tools import ConversationMessage, ToolDefinition, ToolTurn


class ScriptedClient:
    """`LlmClient`, отвечающий функцией `(system, user) -> текст` (синхронной или нет).

    `usage=(tokens_in, tokens_out, cache_read, cache_write)` имитирует подсчёт токенов
    провайдером: так проверяются стоимость прогона и бюджет.
    """

    def __init__(
        self,
        complete: Callable[[str, str], Any] | None = None,
        *,
        usage: tuple[int, int, int, int] | None = None,
    ) -> None:
        self._complete = complete
        self._usage = usage
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
        if self._usage is not None:
            tokens_in, tokens_out, cache_read, cache_write = self._usage
            record_usage(
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cache_read=cache_read,
                cache_write=cache_write,
            )
        return result

    async def complete_with_tools(
        self,
        system: str,
        messages: Sequence[ConversationMessage],
        tools: Sequence[ToolDefinition],
        *,
        max_tokens: int,
        effort: str | None = None,
    ) -> ToolTurn:
        """Записанный клиент обычного конвейера агентные ходы не поддерживает."""
        del system, messages, tools, max_tokens, effort
        raise RuntimeError("Записанный клиент конвейера не отвечает на агентные ходы")

    async def count_tokens(self, system: str, user: str) -> int:
        return max((len(system) + len(user)) // 2, 1)

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
        usage: tuple[int, int, int, int] | None = None,
        **options: Any,
    ) -> None:
        super().__init__(
            ScriptedClient(complete, usage=usage), provider=provider, model=model, **options
        )


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
