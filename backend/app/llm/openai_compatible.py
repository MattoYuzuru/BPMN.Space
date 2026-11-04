"""Chat Completions по HTTP: DeepSeek, OpenRouter, vLLM и любой совместимый сервер.

Асинхронный `httpx`: отмена прогона прерывает запрос и паузу между повторами, а не оставляет
поток с оплаченным запросом. Адрес пользователя проверяет `net_guard` перед каждым вызовом.
"""

import json
from collections.abc import Iterable, Sequence
from typing import Any

import httpx

from app.llm.base import (
    CONTEXT_OVERFLOW_MESSAGE,
    ContextOverflowError,
    OutputTruncatedError,
    is_context_overflow,
    record_usage,
)
from app.llm.capabilities import ModelCapabilities, capabilities_for, is_deepseek
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
from app.llm.net_guard import UnsafeBaseUrlError, ensure_public_host, normalize_base_url
from app.llm.pinned_transport import Resolver, pinned_transport
from app.llm.tools import ConversationMessage, ToolDefinition, ToolTurn, ToolUse

_CHAT_MAX_TOKENS = 4096
_HTTP_ERROR = 400
_ERROR_SNIFF_BYTES = 4096
_REFUSAL_FINISH_REASONS = frozenset({"content_filter"})


def _retry_after(response: httpx.Response) -> float | None:
    """`Retry-After` в секундах (форму с датой не разбираем: достаточно обычной паузы)."""
    value = response.headers.get("Retry-After")
    try:
        seconds = float(value) if value is not None else None
    except ValueError:
        return None
    return seconds if seconds is not None and seconds >= 0 else None


class OpenAICompatibleClient:
    """Универсальный адаптер Chat Completions."""

    # Имя параметра лимита ответа: у новых моделей OpenAI оно другое.
    token_param = "max_tokens"  # noqa: S105 — имя поля API, не секрет
    default_base_url: str | None = None
    provider = "openai_compatible"

    def __init__(
        self,
        config: LlmConfig,
        *,
        guard_host: bool = False,
        allowed_private_hosts: Iterable[str] = (),
        policy: RetryPolicy | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: Resolver | None = None,
    ) -> None:
        # Адрес фиксированных провайдеров (OpenAI) нельзя переопределить конфигурацией.
        base_url = self.default_base_url or config.base_url
        if not base_url:
            raise ValueError("Не задан адрес провайдера")
        self._allowed_private = tuple(allowed_private_hosts)
        # Адреса из настроек оператора доверенные; адреса пользователей — только через guard.
        self._base_url = (
            normalize_base_url(base_url, allowed_private_hosts=self._allowed_private)
            if guard_host
            else _operator_url(base_url)
        )
        self._guard_host = guard_host
        self._config = config
        self._policy = policy or RetryPolicy(
            max_retries=max(config.max_retries, 0),
            base_sec=config.retry_base_sec,
            max_sec=config.retry_max_sec,
        )
        if guard_host and transport is None:
            # Соединение идёт к IP, проверенному guard, а не к повторно разрешённому имени.
            transport = pinned_transport(
                allowed_private_hosts=self._allowed_private, resolver=resolver
            )
        # `trust_env=False`: прокси из окружения обошёл бы закреплённый транспорт.
        self._http = httpx.AsyncClient(
            transport=transport, follow_redirects=False, trust_env=not guard_host
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    def build_body(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool,
        max_tokens: int,
        effort: str | None = None,
    ) -> dict[str, Any]:
        config = self._config
        body: dict[str, Any] = {
            "model": config.model,
            "stream": False,
            self.token_param: max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_mode and config.json_mode:
            body["response_format"] = {"type": "json_object"}
        if json_mode and config.json_temperature is not None and self.accepts_temperature():
            body["temperature"] = config.json_temperature
        thinking = self.thinking_for(effort)
        if thinking is not None:
            body["thinking"] = {"type": "enabled" if thinking else "disabled"}
        self.apply_effort(body, effort)
        return body

    def capabilities(self) -> ModelCapabilities:
        return capabilities_for(self.provider, self._config.model, base_url=self._base_url)

    def thinking_for(self, effort: str | None) -> bool | None:
        """`thinking` DeepSeek: только для `api.deepseek.com`, а не по имени модели.

        `low` выключает рассуждение, `high` и выше включают, `medium` и отсутствие уровня
        оставляют настройку сервера (`DEEPSEEK_THINKING_ENABLED` у legacy-провайдера): профиль
        «обычно» не выключает то, что включил оператор.
        """
        if effort is None or effort == "medium" or not is_deepseek(self._base_url):
            return self._config.thinking
        return effort != "low"

    def apply_effort(self, body: dict[str, Any], effort: str | None) -> None:
        """Совместимые серверы, кроме DeepSeek, уровень не принимают: поле не отправляется."""

    def accepts_temperature(self) -> bool:
        return True

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._config.api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }

    async def complete(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool,
        max_tokens: int,
        effort: str | None = None,
    ) -> str:
        limit = max_tokens if json_mode else min(max_tokens, _CHAT_MAX_TOKENS)
        body = self.build_body(system, user, json_mode=json_mode, max_tokens=limit, effort=effort)
        raw = await self._post("/chat/completions", body)
        try:
            payload = json.loads(raw)
            choice = payload["choices"][0]
            usage = payload.get("usage") or {}
            cache_read = _cache_read_tokens(usage)
            cache_write = _cache_write_tokens(usage)
            record_usage(
                # `prompt_tokens` у OpenAI и DeepSeek включает и попадания в кеш.
                tokens_in=token_count(usage.get("prompt_tokens")),
                tokens_out=token_count(usage.get("completion_tokens")),
                cache_read=cache_read,
                cache_write=cache_write,
            )
            if choice.get("finish_reason") == "length":
                raise OutputTruncatedError(
                    "Ответ модели обрезан по лимиту длины: результат неполный и не применён"
                )
            message = choice["message"]
            if message.get("refusal"):
                raise LlmRefusalError(
                    "Модель отказалась отвечать на этот запрос. "
                    "Измените материалы или выберите другую модель"
                )
            content = message["content"]
            if not isinstance(content, str) or not content.strip():
                raise RuntimeError("Модель вернула пустой или неподдерживаемый ответ")
            return content
        except json.JSONDecodeError:
            raise RuntimeError("Сервис модели вернул ответ в некорректном формате") from None
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            raise RuntimeError("Сервис модели вернул ответ неизвестной структуры") from None

    def build_tools_body(
        self,
        system: str,
        messages: Sequence[ConversationMessage],
        tools: Sequence[ToolDefinition],
        *,
        max_tokens: int,
        effort: str | None = None,
    ) -> dict[str, Any]:
        """Тело агентного хода: `tools`/`tool_calls` Chat Completions, без JSON-режима."""
        body: dict[str, Any] = {
            "model": self._config.model,
            "stream": False,
            self.token_param: max_tokens,
            "messages": [
                {"role": "system", "content": system},
                *_tool_messages(messages),
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.input_schema,
                    },
                }
                for tool in tools
            ],
        }
        thinking = self.thinking_for(effort)
        if thinking is not None:
            body["thinking"] = {"type": "enabled" if thinking else "disabled"}
        self.apply_effort(body, effort)
        return body

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
        body = self.build_tools_body(system, messages, tools, max_tokens=max_tokens, effort=effort)
        raw = await self._post("/chat/completions", body)
        try:
            payload = json.loads(raw)
            choice = payload["choices"][0]
            usage = payload.get("usage") or {}
            record_usage(
                tokens_in=token_count(usage.get("prompt_tokens")),
                tokens_out=token_count(usage.get("completion_tokens")),
                cache_read=_cache_read_tokens(usage),
                cache_write=_cache_write_tokens(usage),
            )
            finish = choice.get("finish_reason")
            if finish == "length":
                raise OutputTruncatedError(
                    "Ответ модели обрезан по лимиту длины: результат неполный и не применён"
                )
            message = choice["message"]
            if message.get("refusal") or finish in _REFUSAL_FINISH_REASONS:
                raise LlmRefusalError(
                    "Модель отказалась отвечать на этот запрос. "
                    "Измените материалы или выберите другую модель"
                )
            uses = _tool_uses(message.get("tool_calls"))
            content = message.get("content")
            text = content.strip() if isinstance(content, str) else ""
            if not uses and not text:
                raise RuntimeError("Модель вернула пустой ответ без запросов инструментов")
            return ToolTurn(text=text or None, tool_uses=uses, stop_reason=finish)
        except json.JSONDecodeError:
            raise RuntimeError("Сервис модели вернул ответ в некорректном формате") from None
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            raise RuntimeError("Сервис модели вернул ответ неизвестной структуры") from None

    async def list_models(self) -> list[ModelInfo]:
        raw = await self._request("GET", "/models", None, timeout_sec=15.0, retries=False)
        try:
            items = json.loads(raw)["data"]
            ids = sorted({str(item["id"]) for item in items})
        except (json.JSONDecodeError, KeyError, TypeError):
            raise RuntimeError("Сервис модели вернул ответ неизвестной структуры") from None
        return [ModelInfo(id=name, label=name) for name in ids if self.is_chat_model(name)]

    async def count_tokens(self, system: str, user: str) -> int:
        """Chat Completions не умеет считать токены бесплатно — делится на `chars_per_token`."""
        return approximate_tokens(system, user, self.capabilities())

    def is_chat_model(self, model_id: str) -> bool:  # noqa: ARG002
        return True

    async def _read_capped(self, response: httpx.Response) -> bytes:
        """Читает тело потоком и обрывает его, как только оно превысило потолок."""
        limit = self._config.max_response_bytes
        message = "Сервис модели вернул слишком большой ответ"
        declared = response.headers.get("Content-Length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            raise RuntimeError(message)
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > limit:
                raise RuntimeError(message)
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    async def _overflow(response: httpx.Response) -> bool:
        """Признак «вход длиннее окна» в начале тела ошибки; само тело никуда не уходит."""
        if response.status_code not in {400, 413}:
            return False
        head = b""
        async for chunk in response.aiter_bytes():
            head += chunk
            if len(head) >= _ERROR_SNIFF_BYTES:
                break
        return is_context_overflow(
            response.status_code, head[:_ERROR_SNIFF_BYTES].decode("utf-8", "replace")
        )

    async def _post(self, path: str, body: dict[str, Any]) -> bytes:
        return await self._request("POST", path, body, timeout_sec=self._config.timeout_sec)

    async def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        *,
        timeout_sec: float,
        retries: bool = True,
    ) -> bytes:
        if self._guard_host:
            try:
                await ensure_public_host(
                    self._base_url, allowed_private_hosts=self._allowed_private
                )
            except UnsafeBaseUrlError as error:
                raise RuntimeError(str(error)) from None
        url = f"{self._base_url}{path}"
        content = json.dumps(body).encode() if body is not None else None

        async def once(attempt_timeout: float) -> bytes:
            try:
                async with self._http.stream(
                    method, url, content=content, headers=self._headers(), timeout=attempt_timeout
                ) as response:
                    status = response.status_code
                    if status in {401, 403}:
                        raise LlmAuthError(auth_message(status))
                    if status in RETRYABLE_HTTP:
                        raise TransientLlmError(
                            f"HTTP {status}",
                            f"Сервис модели вернул HTTP {status}",
                            retry_after=_retry_after(response),
                        )
                    if status >= _HTTP_ERROR:
                        if await self._overflow(response):
                            raise ContextOverflowError(CONTEXT_OVERFLOW_MESSAGE)
                        raise RuntimeError(f"Сервис модели вернул HTTP {status}")
                    return await self._read_capped(response)
            except UnsafeBaseUrlError as error:
                raise RuntimeError(str(error)) from None
            except httpx.TimeoutException:
                raise TransientLlmError(
                    "таймаут", timeout_message(timeout_sec), timeout=True
                ) from None
            except httpx.TransportError:
                raise TransientLlmError("сеть", NETWORK_MESSAGE) from None

        if not retries:
            policy = RetryPolicy(max_retries=0)
            return await with_retries(once, policy=policy, timeout_sec=timeout_sec)
        return await with_retries(once, policy=self._policy, timeout_sec=timeout_sec)


def _operator_url(raw: str) -> str:
    """Адрес из настроек оператора: HTTPS, либо HTTP для localhost (как раньше)."""
    return normalize_base_url(raw, allowed_private_hosts=("localhost", "127.0.0.1", "::1"))


def _tool_messages(messages: Sequence[ConversationMessage]) -> list[dict[str, Any]]:
    """Общий разговор → сообщения Chat Completions: assistant с `tool_calls`, затем `tool`."""
    converted: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "tool":
            converted.append(
                {
                    "role": "tool",
                    "tool_call_id": message.tool_use_id,
                    "content": message.text,
                }
            )
        elif message.role == "user":
            converted.append({"role": "user", "content": message.text})
        else:
            item: dict[str, Any] = {"role": "assistant", "content": message.text or None}
            if message.tool_uses:
                item["tool_calls"] = [
                    {
                        "id": use.id,
                        "type": "function",
                        "function": {"name": use.name, "arguments": use.arguments},
                    }
                    for use in message.tool_uses
                ]
            converted.append(item)
    return converted


def _tool_uses(raw: object) -> tuple[ToolUse, ...]:
    """`tool_calls` ответа OpenAI: имя обязательно, отсутствующий id заменяется стабильным."""
    if not isinstance(raw, list):
        return ()
    uses: list[ToolUse] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError("tool_calls: ожидался объект")
        function = item.get("function")
        if not isinstance(function, dict):
            raise ValueError("tool_calls: нет function")
        name = function.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("tool_calls: нет имени функции")
        arguments = function.get("arguments")
        if isinstance(arguments, dict):
            arguments = json.dumps(arguments, ensure_ascii=False)
        if not isinstance(arguments, str) or not arguments.strip():
            arguments = "{}"
        call_id = item.get("id")
        uses.append(
            ToolUse(
                id=call_id if isinstance(call_id, str) and call_id else f"call_{index}",
                name=name,
                arguments=arguments,
            )
        )
    return tuple(uses)


def _cache_read_tokens(usage: dict[str, Any]) -> int:
    """Токены, прочитанные из кеша: OpenAI, DeepSeek и совместимые называют их по-разному."""
    details = usage.get("prompt_tokens_details")
    if isinstance(details, dict):
        cached = token_count(details.get("cached_tokens"))
        if cached:
            return cached
    for key in ("prompt_cache_hit_tokens", "cache_read_input_tokens", "cached_tokens"):
        value = token_count(usage.get(key))
        if value is not None:
            return value
    return 0


def _cache_write_tokens(usage: dict[str, Any]) -> int:
    """Токены, записанные в кеш (у большинства совместимых провайдеров их нет)."""
    details = usage.get("prompt_tokens_details")
    if isinstance(details, dict):
        written = token_count(details.get("cache_write_tokens"))
        if written:
            return written
    for key in ("cache_creation_input_tokens",):
        value = token_count(usage.get(key))
        if value is not None:
            return value
    return 0
