"""Anthropic через официальный SDK (`anthropic`), асинхронно и со стримингом.

Правила API 2026-10: `temperature`/`top_p`/`top_k` не отправляются (400); рассуждение у Opus и
Sonnet 5.5 отключить нельзя — параметр `thinking` не передаётся, глубину задаёт
`output_config.effort` на каждый запрос (профиль прогона → явный `LLM_ANTHROPIC_EFFORT` →
умолчание модели из каталога); prefill ассистента запрещён. Большие `max_tokens` (до 128 тыс.
у моделей 5.5) обязаны идти потоком, поэтому всегда `messages.stream(...).get_final_message()`.
Верхнеуровневый `cache_control` кэширует стабильную часть запроса: порции источников повторяют
один префикс (system + схема).
Повторы выполняет приложение (`max_retries=0` у SDK): так они не удваиваются и учитывают срок.
"""

import json
from collections.abc import Sequence

import anthropic
import httpx2

from app.llm.base import (
    CONTEXT_OVERFLOW_MESSAGE,
    ContextOverflowError,
    OutputTruncatedError,
    is_context_overflow,
    record_usage,
)
from app.llm.capabilities import capabilities_for, from_anthropic_model, remember, wire_effort
from app.llm.client import (
    NETWORK_MESSAGE,
    RETRYABLE_HTTP,
    LlmAuthError,
    LlmConfig,
    LlmRefusalError,
    ModelInfo,
    RetryPolicy,
    TransientLlmError,
    approximate_tokens,
    auth_message,
    timeout_message,
    token_count,
    with_retries,
)
from app.llm.multimodal import MediaAttachment
from app.llm.tools import ConversationMessage, ToolDefinition, ToolTurn, ToolUse

_JSON_ONLY = (
    "\n\nОтветь одним JSON-объектом без markdown-обёртки и без текста вне JSON. "
    "Формат и поля — строго по схеме выше."
)
_CHAT_MAX_TOKENS = 4096
_HTTP_ERROR = 400


def _retry_after(error: anthropic.APIStatusError) -> float | None:
    try:
        return max(float(error.response.headers["retry-after"]), 0.0)
    except (KeyError, ValueError, TypeError):
        return None


def _record_usage(message: anthropic.types.Message) -> None:
    """Токены ответа Anthropic: обычный вход, чтение и запись кеша — как в `complete`."""
    usage = message.usage
    cached = token_count(getattr(usage, "cache_read_input_tokens", 0)) or 0
    created = token_count(getattr(usage, "cache_creation_input_tokens", 0)) or 0
    input_tokens = token_count(usage.input_tokens) or 0
    record_usage(
        # `tokens_in` — все входные токены: обычный вход, чтение и запись кеша.
        tokens_in=input_tokens + cached + created,
        tokens_out=token_count(usage.output_tokens),
        cache_read=cached,
        cache_write=created,
    )


def _stop_error(message: anthropic.types.Message) -> None:
    """Обрезка и отказ модели — ошибки, а не пустой ответ."""
    if message.stop_reason == "max_tokens":
        raise OutputTruncatedError(
            "Ответ модели обрезан по лимиту длины: результат неполный и не применён"
        )
    if message.stop_reason == "refusal":
        raise LlmRefusalError(
            "Модель отказалась отвечать на этот запрос. "
            "Измените материалы или выберите другую модель"
        )


def _text_of(message: anthropic.types.Message) -> str:
    return "".join(block.text for block in message.content if block.type == "text")


def _tool_messages(messages: Sequence[ConversationMessage]) -> list[dict[str, object]]:
    """Общий разговор → сообщения Anthropic; результаты подряд идут одним user-сообщением.

    API требует: после assistant с `tool_use` следующий user содержит `tool_result` на каждый
    запрос. Несколько параллельных инструментов — один список блоков, а не несколько сообщений.
    """
    converted: list[dict[str, object]] = []
    pending_results: list[dict[str, object]] = []
    for message in messages:
        if message.role == "tool":
            pending_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": message.tool_use_id,
                    "content": message.text,
                    "is_error": message.is_error,
                }
            )
            continue
        if pending_results:
            converted.append({"role": "user", "content": pending_results})
            pending_results = []
        if message.role == "user":
            converted.append({"role": "user", "content": [{"type": "text", "text": message.text}]})
            continue
        blocks: list[dict[str, object]] = []
        if message.text.strip():
            blocks.append({"type": "text", "text": message.text})
        blocks.extend(
            {
                "type": "tool_use",
                "id": use.id,
                "name": use.name,
                "input": use.parsed_arguments(),
            }
            for use in message.tool_uses
        )
        if blocks:
            converted.append({"role": "assistant", "content": blocks})
    if pending_results:
        converted.append({"role": "user", "content": pending_results})
    return converted


def _tool_turn(message: anthropic.types.Message) -> ToolTurn:
    text = _text_of(message).strip()
    uses = tuple(
        ToolUse(id=block.id, name=block.name, arguments=json.dumps(block.input, ensure_ascii=False))
        for block in message.content
        if block.type == "tool_use"
    )
    if not uses and not text:
        raise RuntimeError("Модель вернула пустой ответ без запросов инструментов")
    return ToolTurn(text=text or None, tool_uses=uses, stop_reason=message.stop_reason)


class AnthropicClient:
    def __init__(
        self,
        config: LlmConfig,
        *,
        policy: RetryPolicy | None = None,
        http_client: httpx2.AsyncClient | None = None,
        sdk: anthropic.AsyncAnthropic | None = None,
    ) -> None:
        self._config = config
        self._policy = policy or RetryPolicy(
            max_retries=max(config.max_retries, 0),
            base_sec=config.retry_base_sec,
            max_sec=config.retry_max_sec,
        )
        self._sdk = sdk or anthropic.AsyncAnthropic(
            api_key=config.api_key.get_secret_value(),
            max_retries=0,
            timeout=config.timeout_sec,
            http_client=http_client,
        )

    async def aclose(self) -> None:
        await self._sdk.close()

    def build_request(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool,
        max_tokens: int,
        effort: str | None = None,
    ) -> dict[str, object]:
        request: dict[str, object] = {
            "model": self._config.model,
            "max_tokens": max_tokens if json_mode else min(max_tokens, _CHAT_MAX_TOKENS),
            "system": [{"type": "text", "text": system + (_JSON_ONLY if json_mode else "")}],
            "messages": [{"role": "user", "content": user}],
            "cache_control": {"type": "ephemeral"},
        }
        level = self.effort_for(effort)
        if level is not None:
            request["output_config"] = {"effort": level}
        return request

    def effort_for(self, requested: str | None) -> str | None:
        """Уровень запроса: от пайплайна — как есть (он уже проверен и записан в прогоне);
        без него — умолчание сервера, затем модели; `None` — не отправлять."""
        if requested is not None:
            return requested
        caps = capabilities_for("anthropic", self._config.model)
        return wire_effort("anthropic", caps, None, server_default=self._config.effort)

    async def complete(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool,
        max_tokens: int,
        effort: str | None = None,
    ) -> str:
        request = self.build_request(
            system, user, json_mode=json_mode, max_tokens=max_tokens, effort=effort
        )
        return await self._run(request)

    async def complete_vision(
        self,
        system: str,
        user: str,
        *,
        images: Sequence[MediaAttachment],
        json_mode: bool,
        max_tokens: int,
        effort: str | None = None,
    ) -> str:
        """Изображения уходят блоками `image` рядом с текстом запроса (RFC-0006)."""
        content: list[dict[str, object]] = [{"type": "text", "text": user}]
        content.extend(_image_block(image) for image in images)
        request = self.build_media_request(
            system, content, json_mode=json_mode, max_tokens=max_tokens, effort=effort
        )
        return await self._run(request)

    async def complete_document(
        self,
        system: str,
        user: str,
        *,
        document: MediaAttachment,
        json_mode: bool,
        max_tokens: int,
        effort: str | None = None,
    ) -> str:
        """PDF читает сама модель: блок `document` (до 32 МБ и 600 страниц, RFC-0006)."""
        content: list[dict[str, object]] = [
            {"type": "text", "text": user},
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": document.mime,
                    "data": document.base64_data,
                },
            },
        ]
        request = self.build_media_request(
            system, content, json_mode=json_mode, max_tokens=max_tokens, effort=effort
        )
        return await self._run(request)

    def build_media_request(
        self,
        system: str,
        content: list[dict[str, object]],
        *,
        json_mode: bool,
        max_tokens: int,
        effort: str | None,
    ) -> dict[str, object]:
        """Запрос с нетекстовыми блоками: параметры те же, что у `build_request`.

        Без `cache_control`: OCR и описание кадров — разовые запросы без повторяющегося
        префикса, а запись кеша стоит 1,25× цены входа. Кеш остаётся только у прогонов, где
        порции источников повторяют один system + схему.
        """
        request: dict[str, object] = {
            "model": self._config.model,
            "max_tokens": max_tokens if json_mode else min(max_tokens, _CHAT_MAX_TOKENS),
            "system": [{"type": "text", "text": system + (_JSON_ONLY if json_mode else "")}],
            "messages": [{"role": "user", "content": content}],
        }
        level = self.effort_for(effort)
        if level is not None:
            request["output_config"] = {"effort": level}
        return request

    async def _run(self, request: dict[str, object]) -> str:
        """Один запрос (стриминг обязателен): повторы, учёт токенов, проверка завершения."""

        async def once(attempt_timeout: float) -> anthropic.types.Message:
            try:
                async with self._sdk.messages.stream(**request, timeout=attempt_timeout) as stream:  # type: ignore[arg-type]
                    return await stream.get_final_message()
            except anthropic.APITimeoutError:
                raise TransientLlmError(
                    "таймаут", timeout_message(self._config.timeout_sec), timeout=True
                ) from None
            except anthropic.APIConnectionError:
                raise TransientLlmError("сеть", NETWORK_MESSAGE) from None
            except anthropic.APIStatusError as error:
                raise _map_status(error) from None

        message = await with_retries(
            once, policy=self._policy, timeout_sec=self._config.timeout_sec
        )
        _record_usage(message)
        _stop_error(message)
        text = _text_of(message)
        if not text.strip():
            raise RuntimeError("Модель вернула пустой или неподдерживаемый ответ")
        return text

    def build_tools_request(
        self,
        system: str,
        messages: Sequence[ConversationMessage],
        tools: Sequence[ToolDefinition],
        *,
        max_tokens: int,
        effort: str | None = None,
    ) -> dict[str, object]:
        """Запрос агентного хода: тот же кешируемый префикс и effort, плюс описания инструментов."""
        request: dict[str, object] = {
            "model": self._config.model,
            "max_tokens": max_tokens,
            "system": [{"type": "text", "text": system}],
            "messages": _tool_messages(messages),
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                }
                for tool in tools
            ],
            "cache_control": {"type": "ephemeral"},
        }
        level = self.effort_for(effort)
        if level is not None:
            request["output_config"] = {"effort": level}
        return request

    async def complete_with_tools(
        self,
        system: str,
        messages: Sequence[ConversationMessage],
        tools: Sequence[ToolDefinition],
        *,
        max_tokens: int,
        effort: str | None = None,
    ) -> ToolTurn:
        if not tools:
            raise ValueError("Агентный ход требует хотя бы одного инструмента")
        request = self.build_tools_request(
            system, messages, tools, max_tokens=max_tokens, effort=effort
        )

        async def once(attempt_timeout: float) -> anthropic.types.Message:
            try:
                async with self._sdk.messages.stream(**request, timeout=attempt_timeout) as stream:  # type: ignore[arg-type]
                    return await stream.get_final_message()
            except anthropic.APITimeoutError:
                raise TransientLlmError(
                    "таймаут", timeout_message(self._config.timeout_sec), timeout=True
                ) from None
            except anthropic.APIConnectionError:
                raise TransientLlmError("сеть", NETWORK_MESSAGE) from None
            except anthropic.APIStatusError as error:
                raise _map_status(error) from None

        message = await with_retries(
            once, policy=self._policy, timeout_sec=self._config.timeout_sec
        )
        _record_usage(message)
        _stop_error(message)
        return _tool_turn(message)

    async def count_tokens(self, system: str, user: str) -> int:
        """Точное число входных токенов бесплатным `messages.count_tokens`.

        Вызывается до запуска, когда ключ ещё не подтверждён рабочим запросом модели: сбой
        счётчика не должен ломать оценку, поэтому при ошибке возвращается оценка по знакам.
        """
        try:
            result = await self._sdk.messages.count_tokens(
                model=self._config.model,
                system=[{"type": "text", "text": system}],
                messages=[{"role": "user", "content": user}],
                timeout=10.0,
            )
            counted = token_count(getattr(result, "input_tokens", None))
            if counted:
                return counted
        except (anthropic.APIStatusError, anthropic.APIConnectionError, anthropic.APITimeoutError):
            pass
        return approximate_tokens(system, user, capabilities_for("anthropic", self._config.model))

    async def list_models(self) -> list[ModelInfo]:
        try:
            page = await self._sdk.models.list(limit=100, timeout=15.0)
        except anthropic.APITimeoutError:
            raise RuntimeError(timeout_message(15.0)) from None
        except anthropic.APIConnectionError:
            raise RuntimeError(NETWORK_MESSAGE) from None
        except anthropic.APIStatusError as error:
            mapped = _map_status(error)
            if isinstance(mapped, TransientLlmError):
                raise RuntimeError(mapped.message) from None
            raise mapped from None
        models: list[ModelInfo] = []
        for item in page.data:
            # Окно, максимум ответа и уровни effort из Models API уточняют каталог.
            caps = from_anthropic_model(item)
            remember("anthropic", item.id, caps)
            models.append(
                ModelInfo(id=item.id, label=item.display_name or item.id, capabilities=caps)
            )
        return models


def _image_block(image: MediaAttachment) -> dict[str, object]:
    """Блок изображения Anthropic: base64 из локального файла (кадры ffmpeg — JPEG)."""
    if image.kind != "image":
        raise ValueError("Ожидалось изображение")
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": image.mime, "data": image.base64_data},
    }


def _map_status(error: anthropic.APIStatusError) -> TransientLlmError | RuntimeError:
    status = error.status_code
    if status in {401, 403}:
        return LlmAuthError(auth_message(status))
    if status in RETRYABLE_HTTP:
        return TransientLlmError(
            f"HTTP {status}", f"Сервис модели вернул HTTP {status}", retry_after=_retry_after(error)
        )
    # Текст ошибки только проверяется на признак переполнения и в сообщение не попадает.
    if is_context_overflow(status, str(getattr(error, "message", "") or "")):
        return ContextOverflowError(CONTEXT_OVERFLOW_MESSAGE)
    return RuntimeError(f"Сервис модели вернул HTTP {status}")
