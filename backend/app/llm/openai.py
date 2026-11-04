"""Официальный API OpenAI: Chat Completions с `max_completion_tokens`.

Рассуждающие модели (o-серия, gpt-5) принимают только температуру по умолчанию, поэтому для них
`temperature` не отправляется; для классических `gpt-4*` остаётся 0 в JSON-запросах.
"""

from app.llm.openai_compatible import OpenAICompatibleClient

OPENAI_BASE_URL = "https://api.openai.com/v1"
_NOT_CHAT = ("embedding", "whisper", "tts", "dall-e", "moderation", "davinci", "babbage", "image")


class OpenAIClient(OpenAICompatibleClient):
    token_param = "max_completion_tokens"  # noqa: S105 — имя поля API, не секрет
    default_base_url = OPENAI_BASE_URL

    def accepts_temperature(self) -> bool:
        return self._config.model.lower().startswith(("gpt-4", "chatgpt-4"))

    def is_chat_model(self, model_id: str) -> bool:
        name = model_id.lower()
        return name.startswith(("gpt-", "o1", "o3", "o4", "chatgpt-")) and not any(
            marker in name for marker in _NOT_CHAT
        )
