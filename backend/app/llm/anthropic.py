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

import anthropic
import httpx2

from app.llm.base import OutputTruncatedError, record_usage
from app.llm.capabilities import capabilities_for, from_anthropic_model, nearest_effort, remember
from app.llm.client import (
    NETWORK_MESSAGE,
    RETRYABLE_HTTP,
    LlmAuthError,
    LlmConfig,
    LlmRefusalError,
    ModelInfo,
    RetryPolicy,
    TransientLlmError,
    auth_message,
    timeout_message,
    token_count,
    with_retries,
)

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
        """Уровень запроса: профиль → умолчание сервера → умолчание модели; `None` — не слать."""
        caps = capabilities_for("anthropic", self._config.model)
        wanted = requested or self._config.effort or caps.effort_default
        if wanted is None:
            return None
        return nearest_effort(wanted, caps.effort_levels)

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
        usage = message.usage
        cached = token_count(getattr(usage, "cache_read_input_tokens", 0)) or 0
        created = token_count(getattr(usage, "cache_creation_input_tokens", 0)) or 0
        record_usage(
            tokens_in=(token_count(usage.input_tokens) or 0) + cached + created,
            tokens_out=token_count(usage.output_tokens),
        )
        if message.stop_reason == "max_tokens":
            raise OutputTruncatedError(
                "Ответ модели обрезан по лимиту длины: результат неполный и не применён"
            )
        if message.stop_reason == "refusal":
            raise LlmRefusalError(
                "Модель отказалась отвечать на этот запрос. "
                "Измените материалы или выберите другую модель"
            )
        text = "".join(block.text for block in message.content if block.type == "text")
        if not text.strip():
            raise RuntimeError("Модель вернула пустой или неподдерживаемый ответ")
        return text

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


def _map_status(error: anthropic.APIStatusError) -> TransientLlmError | RuntimeError:
    status = error.status_code
    if status in {401, 403}:
        return LlmAuthError(auth_message(status))
    if status in RETRYABLE_HTTP:
        return TransientLlmError(
            f"HTTP {status}", f"Сервис модели вернул HTTP {status}", retry_after=_retry_after(error)
        )
    return RuntimeError(f"Сервис модели вернул HTTP {status}")
