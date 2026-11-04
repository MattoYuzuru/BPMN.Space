"""Chat Completions по HTTP: DeepSeek, OpenRouter, vLLM и любой совместимый сервер.

Асинхронный `httpx`: отмена прогона прерывает запрос и паузу между повторами, а не оставляет
поток с оплаченным запросом. Адрес пользователя проверяет `net_guard` перед каждым вызовом.
"""

import json
from collections.abc import Iterable
from typing import Any

import httpx

from app.llm.base import OutputTruncatedError, record_usage
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
from app.llm.net_guard import UnsafeBaseUrlError, ensure_public_host, normalize_base_url

_CHAT_MAX_TOKENS = 4096
_HTTP_ERROR = 400


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

    def __init__(
        self,
        config: LlmConfig,
        *,
        guard_host: bool = False,
        allowed_private_hosts: Iterable[str] = (),
        policy: RetryPolicy | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
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
        self._http = httpx.AsyncClient(transport=transport, follow_redirects=False)

    async def aclose(self) -> None:
        await self._http.aclose()

    def build_body(
        self, system: str, user: str, *, json_mode: bool, max_tokens: int
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
        if config.thinking is not None:
            body["thinking"] = {"type": "enabled" if config.thinking else "disabled"}
        return body

    def accepts_temperature(self) -> bool:
        return True

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._config.api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }

    async def complete(self, system: str, user: str, *, json_mode: bool, max_tokens: int) -> str:
        limit = max_tokens if json_mode else min(max_tokens, _CHAT_MAX_TOKENS)
        body = self.build_body(system, user, json_mode=json_mode, max_tokens=limit)
        raw = await self._post("/chat/completions", body)
        try:
            payload = json.loads(raw)
            choice = payload["choices"][0]
            usage = payload.get("usage") or {}
            record_usage(
                tokens_in=token_count(usage.get("prompt_tokens")),
                tokens_out=token_count(usage.get("completion_tokens")),
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

    async def list_models(self) -> list[ModelInfo]:
        raw = await self._request("GET", "/models", None, timeout_sec=15.0, retries=False)
        try:
            items = json.loads(raw)["data"]
            ids = sorted({str(item["id"]) for item in items})
        except (json.JSONDecodeError, KeyError, TypeError):
            raise RuntimeError("Сервис модели вернул ответ неизвестной структуры") from None
        return [ModelInfo(id=name, label=name) for name in ids if self.is_chat_model(name)]

    def is_chat_model(self, model_id: str) -> bool:  # noqa: ARG002
        return True

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
                response = await self._http.request(
                    method, url, content=content, headers=self._headers(), timeout=attempt_timeout
                )
            except httpx.TimeoutException:
                raise TransientLlmError(
                    "таймаут", timeout_message(timeout_sec), timeout=True
                ) from None
            except httpx.TransportError:
                raise TransientLlmError("сеть", NETWORK_MESSAGE) from None
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
                raise RuntimeError(f"Сервис модели вернул HTTP {status}")
            return response.content

        if not retries:
            policy = RetryPolicy(max_retries=0)
            return await with_retries(once, policy=policy, timeout_sec=timeout_sec)
        return await with_retries(once, policy=self._policy, timeout_sec=timeout_sec)


def _operator_url(raw: str) -> str:
    """Адрес из настроек оператора: HTTPS, либо HTTP для localhost (как раньше)."""
    return normalize_base_url(raw, allowed_private_hosts=("localhost", "127.0.0.1", "::1"))
