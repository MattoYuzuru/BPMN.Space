"""Responses API по HTTP (ADR-0013): шлюзы подписки ChatGPT (OpenAI Buffet) и серверы OpenAI.

Транспорт, защита адреса пользователя, потолок ответа и повторы — общие с Chat Completions
(`OpenAICompatibleClient`); меняется только форма запроса и ответа. Запросы не хранятся на
сервере (`store: false`): вся история разговора едет во `input`, системный промпт — в
`instructions`, а рассуждение модели возвращается зашифрованным (`reasoning.encrypted_content`)
и повторяется в следующем ходе инструментов без изменений.

Необязательные параметры (`max_output_tokens`, `temperature`, `reasoning`, `include`) серверы
принимают по-разному: шлюз подписки, например, отвергает лимит ответа и температуру. Клиент
отправляет их, а на явный ответ `400 unsupported_parameter` с именем параметра один раз
повторяет запрос без него и больше этот параметр не шлёт. Прочие ошибки не обходятся.
"""

import json
import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import replace
from typing import Any

import httpx

from app.llm.base import (
    CONTEXT_OVERFLOW_MESSAGE,
    ContextOverflowError,
    OutputTruncatedError,
    is_context_overflow,
    record_usage,
)
from app.llm.capabilities import (
    EFFORT_LEVELS,
    Effort,
    ModelCapabilities,
    capabilities_for,
    nearest_effort,
    remember,
)
from app.llm.client import (
    PROVIDER_COMPATIBLE,
    LlmConfig,
    LlmRefusalError,
    ModelInfo,
    RetryPolicy,
    token_count,
)
from app.llm.multimodal import MediaAttachment, MediaUnsupportedError
from app.llm.openai_compatible import OpenAICompatibleClient
from app.llm.pinned_transport import Resolver
from app.llm.tools import ConversationMessage, ToolDefinition, ToolTurn, ToolUse

logger = logging.getLogger(__name__)

_CHAT_MAX_TOKENS = 4096
# Порядок важен только для сообщений: каждый параметр снимается не больше одного раза.
OPTIONAL_PARAMS = ("max_output_tokens", "temperature", "reasoning", "include")
_UNSUPPORTED_CODES = frozenset({"unsupported_parameter", "unsupported_value", "invalid_parameter"})
_REASONING_KEYS = ("type", "id", "summary", "content", "encrypted_content")
TRUNCATED_MESSAGE = "Ответ модели обрезан по лимиту длины: результат неполный и не применён"
REFUSAL_MESSAGE = (
    "Модель отказалась отвечать на этот запрос. Измените материалы или выберите другую модель"
)


class UnsupportedParameterError(Exception):
    """Сервер прямо отказался от необязательного параметра запроса (HTTP 400)."""

    def __init__(self, params: frozenset[str]) -> None:
        super().__init__(", ".join(sorted(params)))
        self.params = params


def unsupported_params(text: str) -> frozenset[str]:
    """Какие необязательные параметры сервер назвал неподдерживаемыми в теле ошибки 400.

    OpenAI сообщает имя в `error.param` (`reasoning.effort`), шлюз подписки — в тексте
    (`Unsupported by ChatGPT plan route: max_output_tokens, temperature`). Признаётся только
    явный отказ: код `unsupported_*` или слово «unsupported» в сообщении.
    """
    code: object = None
    param: object = None
    message = text
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            code = error.get("code")
            param = error.get("param")
            message = str(error.get("message") or "")
    explicit = code in _UNSUPPORTED_CODES or "unsupported" in message.lower()
    if not explicit:
        return frozenset()
    names = {
        name
        for name in OPTIONAL_PARAMS
        if isinstance(param, str) and (param == name or param.startswith(f"{name}."))
    }
    names.update(
        name
        for name in OPTIONAL_PARAMS
        if re.search(rf"(?<![\w.]){re.escape(name)}(?![\w])", message)
    )
    return frozenset(names)


def catalog_capabilities(item: dict[str, Any], base: ModelCapabilities) -> ModelCapabilities:
    """Описание модели из `/models` сервера поверх осторожных умолчаний (поля необязательны).

    Шлюз подписки отдаёт каталог аккаунта: окно (`context_window`), уровни рассуждения
    (`supported_reasoning_levels`, строки или объекты с `effort`), уровень по умолчанию и
    входные модальности. Чего нет в описании, остаётся как в `base`.
    """
    updates: dict[str, Any] = {}
    context = item.get("context_window")
    if isinstance(context, int) and not isinstance(context, bool) and context > 0:
        updates["context_tokens"] = context
    raw_levels = item.get("supported_reasoning_levels")
    if isinstance(raw_levels, list):
        named = {
            level.get("effort") if isinstance(level, dict) else level
            for level in raw_levels  # type: ignore[reportUnknownVariableType]
        }
        levels: tuple[Effort, ...] = tuple(level for level in EFFORT_LEVELS if level in named)
        updates["effort_levels"] = levels
        default = item.get("default_reasoning_level")
        if default not in levels:
            default = "medium" if "medium" in levels else (levels[0] if levels else None)
        updates["effort_default"] = default
        if levels:
            # Рассуждающие модели принимают только температуру по умолчанию.
            updates["accepts_temperature"] = False
    modalities = item.get("input_modalities")
    if isinstance(modalities, list):
        updates["vision"] = "image" in modalities
    if not updates:
        return base
    return replace(base, known=True, **updates)


class OpenAIResponsesClient(OpenAICompatibleClient):
    """Адаптер Responses API для совместимого провайдера с протоколом `responses`."""

    provider = PROVIDER_COMPATIBLE

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
        super().__init__(
            config,
            guard_host=guard_host,
            allowed_private_hosts=allowed_private_hosts,
            policy=policy,
            transport=transport,
            resolver=resolver,
        )
        # Параметры, от которых сервер уже отказался: на время жизни клиента (одного прогона).
        self._dropped: set[str] = set()

    def accepts_temperature(self) -> bool:
        return self.capabilities().accepts_temperature

    def apply_effort(self, body: dict[str, Any], effort: str | None) -> None:
        """Уровень рассуждения — `reasoning.effort`; без известных уровней поле не шлётся."""
        levels = self.capabilities().effort_levels
        if effort and levels:
            body["reasoning"] = {
                "effort": effort if effort in levels else nearest_effort(effort, levels)
            }

    def _request_body(
        self,
        system: str,
        items: list[dict[str, Any]],
        *,
        max_tokens: int,
        effort: str | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self._config.model,
            "instructions": system,
            "input": items,
            "store": False,
            "stream": False,
            "max_output_tokens": max_tokens,
        }
        self.apply_effort(body, effort)
        return body

    def build_body(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool,
        max_tokens: int,
        effort: str | None = None,
        content: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Тело Responses: промпт в `instructions`, задача — одно сообщение пользователя."""
        config = self._config
        message = {"role": "user", "content": content if content is not None else user}
        body = self._request_body(system, [message], max_tokens=max_tokens, effort=effort)
        if json_mode and config.json_mode:
            body["text"] = {"format": {"type": "json_object"}}
        if json_mode and config.json_temperature is not None and self.accepts_temperature():
            body["temperature"] = config.json_temperature
        return body

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
        return self.parse_completion(await self._send(body))

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
        """Изображения — части `input_image` с data-URL, как у Chat Completions."""
        limit = max_tokens if json_mode else min(max_tokens, _CHAT_MAX_TOKENS)
        content: list[dict[str, Any]] = [{"type": "input_text", "text": user}]
        content.extend({"type": "input_image", "image_url": image.data_url()} for image in images)
        body = self.build_body(
            system, user, json_mode=json_mode, max_tokens=limit, effort=effort, content=content
        )
        return self.parse_completion(await self._send(body))

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
        """PDF — часть `input_file`, только если модель заявляет `pdf_input`."""
        if not self.capabilities().pdf_input:
            raise MediaUnsupportedError(
                "Модель не принимает PDF: выберите модель с чтением PDF или OCR-провайдера"
            )
        limit = max_tokens if json_mode else min(max_tokens, _CHAT_MAX_TOKENS)
        content: list[dict[str, Any]] = [
            {"type": "input_text", "text": user},
            {
                "type": "input_file",
                "filename": document.label or "document.pdf",
                "file_data": document.data_url(),
            },
        ]
        body = self.build_body(
            system, user, json_mode=json_mode, max_tokens=limit, effort=effort, content=content
        )
        return self.parse_completion(await self._send(body))

    def parse_completion(self, raw: bytes) -> str:
        """Текст ответа: части `output_text` всех сообщений; отказ и обрезка — явные ошибки."""
        try:
            payload = json.loads(raw)
            output = self._checked_output(payload)
            texts, refused = _message_texts(output)
            text = "".join(texts)
            if refused and not text.strip():
                raise LlmRefusalError(REFUSAL_MESSAGE)
            if not text.strip():
                raise RuntimeError("Модель вернула пустой или неподдерживаемый ответ")
            return text
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
        """Агентный ход: функции без `strict` (схемы инструментов не обязаны быть строгими)."""
        body = self._request_body(
            system, input_items(messages), max_tokens=max_tokens, effort=effort
        )
        body["tools"] = [
            {
                "type": "function",
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
                "strict": False,
            }
            for tool in tools
        ]
        # Без хранения на сервере рассуждение повторяется только в зашифрованном виде.
        body["include"] = ["reasoning.encrypted_content"]
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
        raw = await self._send(body)
        try:
            payload = json.loads(raw)
            output = self._checked_output(payload)
            texts, refused = _message_texts(output)
            uses = _tool_uses(output)
            text = "".join(texts).strip()
            if refused and not uses and not text:
                raise LlmRefusalError(REFUSAL_MESSAGE)
            if not uses and not text:
                raise RuntimeError("Модель вернула пустой ответ без запросов инструментов")
            return ToolTurn(
                text=text or None,
                tool_uses=uses,
                stop_reason="tool_calls" if uses else str(payload.get("status") or "completed"),
                provider_blocks=_reasoning_blocks(output),
            )
        except json.JSONDecodeError:
            raise RuntimeError("Сервис модели вернул ответ в некорректном формате") from None
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            raise RuntimeError("Сервис модели вернул ответ неизвестной структуры") from None

    async def list_models(self) -> list[ModelInfo]:
        """`GET /models` (как у Chat Completions); описание из каталога запоминается по хосту."""
        raw = await self._request("GET", "/models", None, timeout_sec=15.0, retries=False)
        try:
            items = json.loads(raw)["data"]
            described: dict[str, ModelInfo] = {}
            for item in items:
                model_id = str(item["id"])
                base = capabilities_for(self.provider, model_id, base_url=self._base_url)
                caps = catalog_capabilities(item, base) if isinstance(item, dict) else base
                if caps.known:
                    remember(self.provider, model_id, caps, base_url=self._base_url)
                label = item.get("display_name") if isinstance(item, dict) else None
                described[model_id] = ModelInfo(
                    id=model_id,
                    label=label if isinstance(label, str) and label.strip() else model_id,
                    capabilities=caps if caps.known else None,
                )
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
            raise RuntimeError("Сервис модели вернул ответ неизвестной структуры") from None
        return [described[name] for name in sorted(described)]

    async def http_error(self, response: httpx.Response) -> Exception:
        """400 с явным отказом от необязательного параметра — повод повторить без него."""
        status = response.status_code
        if status in {404, 405, 501}:
            return RuntimeError(
                f"Сервер модели не поддерживает Responses API (HTTP {status}): добавьте ключ "
                "заново с протоколом «Chat Completions»"
            )
        if status != 400:  # noqa: PLR2004 — код ответа HTTP
            return await super().http_error(response)
        head = await self.error_head(response)
        if is_context_overflow(400, head):
            return ContextOverflowError(CONTEXT_OVERFLOW_MESSAGE)
        params = unsupported_params(head)
        if params:
            return UnsupportedParameterError(params)
        return RuntimeError("Сервис модели вернул HTTP 400")

    async def _send(self, body: dict[str, Any]) -> bytes:
        """`POST /responses`; отвергнутые необязательные параметры снимаются по одному разу."""
        for _ in range(len(OPTIONAL_PARAMS) + 1):
            payload = {key: value for key, value in body.items() if key not in self._dropped}
            try:
                return await self._post("/responses", payload)
            except UnsupportedParameterError as error:
                removable = {name for name in error.params if name in payload}
                if not removable:
                    raise RuntimeError(
                        f"Сервер модели не принимает параметр запроса: {error}"
                    ) from None
                logger.info(
                    "Сервер модели %s не принимает %s: параметр больше не отправляется",
                    self._config.model,
                    ", ".join(sorted(removable)),
                )
                self._dropped.update(removable)
        raise RuntimeError("Сервер модели отклонил все варианты запроса")  # pragma: no cover

    @staticmethod
    def _checked_output(payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Учёт токенов и разбор статуса: неполный ответ, отказ и сбой — ошибки, а не текст."""
        usage = payload.get("usage") or {}
        details = usage.get("input_tokens_details") or {}
        record_usage(
            # `input_tokens` включает и прочитанное из кеша, как `prompt_tokens` у Chat.
            tokens_in=token_count(usage.get("input_tokens")),
            tokens_out=token_count(usage.get("output_tokens")),
            cache_read=token_count(details.get("cached_tokens")) or 0,
            cache_write=token_count(details.get("cache_write_tokens")) or 0,
        )
        status = payload.get("status")
        if status == "incomplete":
            reason = (payload.get("incomplete_details") or {}).get("reason")
            if reason == "content_filter":
                raise LlmRefusalError(REFUSAL_MESSAGE)
            raise OutputTruncatedError(TRUNCATED_MESSAGE)
        if status not in (None, "completed"):
            raise RuntimeError(f"Модель не завершила ответ (статус «{status}»)")
        output = payload["output"]
        if not isinstance(output, list):
            raise TypeError("output")
        return [item for item in output if isinstance(item, dict)]  # type: ignore[reportUnknownVariableType]


def input_items(messages: Sequence[ConversationMessage]) -> list[dict[str, Any]]:
    """Общий разговор → `input`: рассуждение, текст и вызовы ассистента, затем их результаты."""
    items: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "user":
            items.append({"role": "user", "content": message.text})
        elif message.role == "tool":
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": message.tool_use_id,
                    "output": message.text,
                }
            )
        else:
            # Блоки другого провайдера (например, `thinking` Anthropic) сюда не попадают.
            items.extend(
                dict(block)
                for block in message.provider_blocks
                if block.get("type") == "reasoning" and block.get("encrypted_content")
            )
            if message.text:
                items.append({"role": "assistant", "content": message.text})
            items.extend(
                {
                    "type": "function_call",
                    "call_id": use.id,
                    "name": use.name,
                    "arguments": use.arguments,
                }
                for use in message.tool_uses
            )
    return items


def _message_texts(output: list[dict[str, Any]]) -> tuple[list[str], bool]:
    texts: list[str] = []
    refused = False
    for item in output:
        if item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if not isinstance(part, dict):
                continue
            kind = part.get("type")  # type: ignore[reportUnknownMemberType]
            if kind == "output_text" and isinstance(part.get("text"), str):  # type: ignore[reportUnknownMemberType]
                texts.append(part["text"])  # type: ignore[reportUnknownArgumentType]
            elif kind == "refusal":
                refused = True
    return texts, refused


def _tool_uses(output: list[dict[str, Any]]) -> tuple[ToolUse, ...]:
    """Элементы `function_call`: имя обязательно, `call_id` связывает вызов с результатом."""
    uses: list[ToolUse] = []
    for index, item in enumerate(output):
        if item.get("type") != "function_call":
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("function_call: нет имени функции")
        arguments = item.get("arguments")
        if isinstance(arguments, dict):
            arguments = json.dumps(arguments, ensure_ascii=False)
        if not isinstance(arguments, str) or not arguments.strip():
            arguments = "{}"
        call_id = item.get("call_id") or item.get("id")
        uses.append(
            ToolUse(
                id=call_id if isinstance(call_id, str) and call_id else f"call_{index}",
                name=name,
                arguments=arguments,
            )
        )
    return tuple(uses)


def _reasoning_blocks(output: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    """Зашифрованное рассуждение для повтора в следующем ходе; без шифртекста — бесполезно."""
    return tuple(
        {key: item[key] for key in _REASONING_KEYS if key in item}
        for item in output
        if item.get("type") == "reasoning" and item.get("encrypted_content")
    )
