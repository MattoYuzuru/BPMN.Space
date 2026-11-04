"""Официальный API OpenAI: Chat Completions с `max_completion_tokens`.

Рассуждающие модели (o-серия, gpt-5) принимают только температуру по умолчанию, поэтому для них
`temperature` не отправляется; для классических `gpt-4*` остаётся 0 в JSON-запросах. Уровень
профиля прогона у рассуждающих моделей уходит в `reasoning_effort` (ближайший из low…high).
"""

from typing import Any

from app.llm.capabilities import nearest_effort
from app.llm.openai_compatible import OpenAICompatibleClient

OPENAI_BASE_URL = "https://api.openai.com/v1"
_NOT_CHAT = ("embedding", "whisper", "tts", "dall-e", "moderation", "davinci", "babbage", "image")


class OpenAIClient(OpenAICompatibleClient):
    token_param = "max_completion_tokens"  # noqa: S105 — имя поля API, не секрет
    default_base_url = OPENAI_BASE_URL
    provider = "openai"

    def accepts_temperature(self) -> bool:
        return self.capabilities().accepts_temperature

    def apply_effort(self, body: dict[str, Any], effort: str | None) -> None:
        """Уровень уже приведён пайплайном (`wire_effort`); у моделей без рассуждения — нет."""
        levels = self.capabilities().effort_levels
        if effort and levels:
            body["reasoning_effort"] = (
                effort if effort in levels else nearest_effort(effort, levels)
            )

    def is_chat_model(self, model_id: str) -> bool:
        name = model_id.lower()
        return name.startswith(("gpt-", "o1", "o3", "o4", "chatgpt-")) and not any(
            marker in name for marker in _NOT_CHAT
        )
