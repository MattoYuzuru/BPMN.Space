"""Сборка пайплайна из `LlmConfig`: провайдер → клиент, настройки сервера → параметры вызова."""

from collections.abc import Iterable

import httpx
import httpx2

from app.config import Settings
from app.llm.anthropic import AnthropicClient
from app.llm.client import PROVIDER_COMPATIBLE, LlmClient, LlmConfig
from app.llm.openai import OpenAIClient
from app.llm.openai_compatible import OpenAICompatibleClient
from app.llm.pipeline import LlmPipeline


def build_client(
    config: LlmConfig,
    *,
    user_supplied_url: bool = False,
    allowed_private_hosts: Iterable[str] = (),
    transport: httpx.AsyncBaseTransport | None = None,
) -> LlmClient:
    """`user_supplied_url` включает защиту от SSRF: так строятся клиенты по ключам пользователей."""
    match config.provider:
        case "anthropic":
            # SDK Anthropic работает на форке `httpx2`: тестовый транспорт для него — из `httpx2`.
            http = None
            if transport is not None:
                http = httpx2.AsyncClient(transport=transport)  # type: ignore[arg-type]
            return AnthropicClient(config, http_client=http)
        case "openai":
            return OpenAIClient(config, transport=transport)
        case "openai_compatible" | "deepseek":
            return OpenAICompatibleClient(
                config,
                guard_host=user_supplied_url,
                allowed_private_hosts=allowed_private_hosts,
                transport=transport,
            )
        case provider:
            raise ValueError(f"Неизвестный провайдер модели: {provider}")


def build_pipeline(
    config: LlmConfig,
    settings: Settings,
    *,
    user_supplied: bool = False,
    transport: httpx.AsyncBaseTransport | None = None,
) -> LlmPipeline:
    """Параметры JSON-ответа берутся из настроек сервера: они общие для всех провайдеров."""
    client = build_client(
        config,
        user_supplied_url=user_supplied and config.provider == PROVIDER_COMPATIBLE,
        allowed_private_hosts=settings.llm_allowed_private_hosts,
        transport=transport,
    )
    return LlmPipeline(
        client,
        provider=PROVIDER_COMPATIBLE if config.provider == "deepseek" else config.provider,
        model=config.model,
        json_mode=config.json_mode,
        semantic_review=settings.llm_semantic_review,
        json_max_tokens=settings.llm_json_max_tokens,
        thinking=config.thinking,
        json_temperature=config.json_temperature,
    )


def call_knobs(settings: Settings) -> dict[str, float | int | bool | str | None]:
    """Общие параметры вызова для любого `LlmConfig`: таймаут, повторы, JSON-режим."""
    runtime = settings.llm_runtime()
    return {
        "timeout_sec": runtime["timeout_sec"],
        "max_retries": runtime["max_retries"],
        "retry_base_sec": runtime["retry_base_sec"],
        "retry_max_sec": runtime["retry_max_sec"],
        "json_mode": settings.llm_json_mode,
        "json_temperature": settings.llm_json_temperature,
        "effort": settings.llm_anthropic_effort,
        "max_response_bytes": settings.llm_max_response_bytes,
    }
