"""Порт к провайдеру модели (ADR-0011): один асинхронный вызов «system + user → текст».

Адаптеры — `openai_compatible.py`, `openai.py`, `anthropic.py`. Пайплайн (`pipeline.py`) не знает,
какой провайдер за ним. Ключ живёт только внутри клиента: в `LlmConfig` он `SecretStr`, а тексты
ошибок адаптеров никогда не включают тело ответа, заголовки и адрес с ключом.
"""

import asyncio
import math
import random
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import SecretStr

from app.llm.base import DEADLINE_MESSAGE, PipelineError, remaining_sec
from app.llm.capabilities import ModelCapabilities

PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_OPENAI = "openai"
PROVIDER_COMPATIBLE = "openai_compatible"
PROVIDER_MOCK = "mock"
USER_PROVIDERS = (PROVIDER_ANTHROPIC, PROVIDER_OPENAI, PROVIDER_COMPATIBLE)

# Таймаут чтения: запрос уже ушёл и, вероятно, оплачен — повторяем не более одного раза.
MAX_READ_TIMEOUT_RETRIES = 1
_MAX_RETRY_AFTER_SEC = 30.0
RETRYABLE_HTTP = frozenset({408, 429, 500, 502, 503, 504, 529})

_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)(api[_-]?key|x-api-key)[\"'=:\s]+[A-Za-z0-9._\-]{8,}"),
)


def redact_secrets(text: str) -> str:
    """Подстраховка для журналов и аудита: похожее на ключ заменяется на `***`."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("***", text)
    return text


class LlmAuthError(RuntimeError):
    """Провайдер отклонил ключ (401/403): ключ неверный, отозван или без доступа к модели."""


class LlmRefusalError(RuntimeError):
    """Модель отказалась отвечать по политике провайдера; повтор тем же запросом бесполезен."""


class TransientLlmError(Exception):
    """Временный сбой, который можно повторить; `message` — итог, если попытки кончились."""

    def __init__(
        self,
        reason: str,
        message: str,
        *,
        retry_after: float | None = None,
        timeout: bool = False,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.message = message
        self.retry_after = retry_after
        self.timeout = timeout


@dataclass(frozen=True, slots=True)
class ModelInfo:
    id: str
    label: str
    # Возможности по каталогу и описанию провайдера; `None` — заполнит сервис по каталогу.
    capabilities: ModelCapabilities | None = None


@dataclass(frozen=True, slots=True)
class LlmConfig:
    """Всё нужное, чтобы построить клиента: ключ не попадает в repr и журналы."""

    provider: str
    model: str
    api_key: SecretStr = field(repr=False)
    base_url: str | None = None
    timeout_sec: float = 120.0
    max_retries: int = 3
    retry_base_sec: float = 1.0
    retry_max_sec: float = 30.0
    json_mode: bool = True
    json_temperature: float | None = 0.0
    thinking: bool | None = None
    # Умолчание effort сервера (`LLM_ANTHROPIC_EFFORT`, только если задан явно); `None` —
    # умолчание модели из каталога. Профиль прогона передаёт свой уровень в `complete`.
    effort: str | None = None
    # Потолок тела ответа сервера модели: пользовательский сервер не должен съесть память.
    max_response_bytes: int = 8 * 1024 * 1024


class LlmClient(Protocol):
    """Провайдер модели. Токены сообщает через `record_usage`, сбои — `RuntimeError`."""

    async def complete(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool,
        max_tokens: int,
        effort: str | None = None,
    ) -> str:
        """`effort` — уровень профиля прогона; адаптер переводит его в параметр провайдера."""
        ...

    async def count_tokens(self, system: str, user: str) -> int:
        """Сколько входных токенов займёт запрос — для оценки стоимости до запуска.

        У Anthropic это бесплатный `messages.count_tokens`; остальные провайдеры такого
        метода не дают, поэтому адаптер делит знаки на `chars_per_token` из справочника
        (замер `prompt-eval` ещё не проводился, значение заведомо осторожное).
        """
        ...

    async def list_models(self) -> list[ModelInfo]:
        """Список моделей аккаунта; одновременно проверяет, что ключ рабочий."""
        ...

    async def aclose(self) -> None: ...


def approximate_tokens(system: str, user: str, capabilities: ModelCapabilities) -> int:
    """Оценка входных токенов по знакам и `chars_per_token` для провайдеров без счётчика."""
    per_token = max(capabilities.chars_per_token, 0.5)
    return max(math.ceil((len(system) + len(user)) / per_token), 1)


@dataclass(slots=True)
class RetryPolicy:
    max_retries: int = 3
    base_sec: float = 1.0
    max_sec: float = 30.0
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    jitter: Callable[[], float] = random.random

    def delay(self, attempt: int, retry_after: float | None) -> float:
        """Экспоненциальная пауза с джиттером; `Retry-After` провайдера — нижняя граница."""
        ceiling = min(self.base_sec * 2**attempt, self.max_sec)
        delay = ceiling / 2 + self.jitter() * ceiling / 2
        if retry_after is not None:
            delay = max(delay, min(retry_after, _MAX_RETRY_AFTER_SEC))
        return delay

    async def wait(
        self, attempt: int, retry_after: float | None, *, limit: int | None = None
    ) -> bool:
        """Спит перед повтором; `False` — повторять нельзя (попытки или срок прогона вышли)."""
        if attempt >= (self.max_retries if limit is None else min(limit, self.max_retries)):
            return False
        delay = self.delay(attempt, retry_after)
        remaining = remaining_sec()
        if remaining is not None and delay >= remaining:
            return False
        await self.sleep(delay)
        return True


def request_timeout(timeout_sec: float) -> float:
    """Таймаут попытки: не дольше срока прогона; вышедший срок — отказ без запроса."""
    remaining = remaining_sec()
    if remaining is None:
        return timeout_sec
    if remaining <= 0:
        raise PipelineError(DEADLINE_MESSAGE)
    return min(timeout_sec, remaining)


async def with_retries[T](
    once: Callable[[float], Awaitable[T]], *, policy: RetryPolicy, timeout_sec: float
) -> T:
    """Повторяет временные сбои: 408/429/5xx и обрыв сети — до лимита, таймаут чтения — один раз.

    Асинхронно: отмена прогона прерывает и запрос, и паузу между повторами.
    """
    timeout_attempt = 0
    for attempt in range(policy.max_retries + 1):
        timeout = request_timeout(timeout_sec)
        try:
            return await once(timeout)
        except TransientLlmError as error:
            if error.timeout:
                if await policy.wait(timeout_attempt, None, limit=MAX_READ_TIMEOUT_RETRIES):
                    timeout_attempt += 1
                    continue
            elif await policy.wait(attempt, error.retry_after):
                continue
            raise RuntimeError(error.message) from None
    raise RuntimeError("Не удалось связаться с сервисом модели")  # pragma: no cover


def token_count(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def auth_message(status: int) -> str:
    return f"Провайдер отклонил ключ (HTTP {status}). Проверьте ключ и доступ к модели в настройках"


def timeout_message(timeout_sec: float) -> str:
    return f"Модель не ответила за {timeout_sec:g} секунд. Повторите попытку."


NETWORK_MESSAGE = "Не удалось связаться с сервисом модели. Проверьте сеть и повторите."
