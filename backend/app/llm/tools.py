"""Провайдеро-независимый формат инструментов для `LlmClient.complete_with_tools` (RFC-0004).

Адаптеры переводят эти структуры в нативный протокол: `tool_use`/`tool_result` у Anthropic,
`tools`/`tool_calls` у OpenAI и совместимых серверов. Агентный цикл (`llm/agent.py`) не знает,
какой провайдер за клиентом, и не разбирает ответ провайдера сам.

`ToolUse.arguments` — сырая JSON-строка от модели (как её вернул провайдер): разбор делает
агентный цикл, чтобы неверные аргументы стали ошибкой инструмента, а не сбоем провайдера.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Literal

# Роли разговора с инструментами: сообщение пользователя (задача), ответ ассистента
# (текст и/или запросы инструментов), результат инструмента (ответ на конкретный запрос).
type ToolRole = Literal["user", "assistant", "tool"]


class ToolArgumentsError(ValueError):
    """Модель прислала аргументы инструмента, которые не являются JSON-объектом."""


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """Описание одного инструмента для API провайдера."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolUse:
    """Запрос модели вызвать инструмент: id нужен для сопоставления с результатом."""

    id: str
    name: str
    arguments: str = "{}"

    def parsed_arguments(self) -> dict[str, Any]:
        """Аргументы как JSON-объект; иначе `ToolArgumentsError` с понятным текстом."""
        try:
            value = json.loads(self.arguments) if self.arguments.strip() else {}
        except json.JSONDecodeError:
            raise ToolArgumentsError("Аргументы инструмента — не JSON") from None
        if not isinstance(value, dict):
            raise ToolArgumentsError("Аргументы инструмента должны быть JSON-объектом")
        return value


@dataclass(frozen=True, slots=True)
class ConversationMessage:
    """Одно сообщение разговора в формате, общем для всех провайдеров.

    - `user`: текст задачи или уточнения;
    - `assistant`: текст модели и/или запросы инструментов;
    - `tool`: результат инструмента (`tool_use_id` обязателен), `is_error` — сбой инструмента.
    """

    role: ToolRole
    text: str = ""
    tool_uses: tuple[ToolUse, ...] = field(default_factory=tuple[ToolUse, ...])
    tool_use_id: str | None = None
    is_error: bool = False

    def __post_init__(self) -> None:
        if self.role == "tool" and not self.tool_use_id:
            raise ValueError("Результату инструмента нужен tool_use_id")
        if self.role != "assistant" and self.tool_uses:
            raise ValueError("Запросы инструментов бывают только в ответе ассистента")


@dataclass(frozen=True, slots=True)
class ToolTurn:
    """Ответ модели в режиме инструментов: текст и запросы инструментов (может быть пусто)."""

    text: str | None = None
    tool_uses: tuple[ToolUse, ...] = field(default_factory=tuple[ToolUse, ...])
    stop_reason: str | None = None

    @property
    def has_actions(self) -> bool:
        return bool(self.tool_uses)
