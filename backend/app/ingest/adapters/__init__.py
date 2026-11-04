"""Реестр адаптеров возможностей (RFC-0006): провайдеры, поддержанные для каждого типа задач.

Адаптер создаётся на время одного вызова по расшифрованному ключу пользователя (или ключу
оператора) и закрывается после. Реестр отвечает на два вопроса: какие провайдеры поддержаны
для возможности и как создать адаптер. Волна 1 знает только `speech_to_text`; заготовки
vision/ocr/video/web/tts описаны контрактами, но в реестре не зарегистрированы.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from uuid import UUID

import httpx

from app.domain.capabilities import Capability, CapabilityError, ErrorClass
from app.ingest.adapters.base import CapabilityAdapter
from app.ingest.adapters.http import AdapterClientFactory
from app.ingest.adapters.ocr import OCR_PROVIDERS, ContractOcrAdapter
from app.ingest.adapters.stt_deepgram import DeepgramSttAdapter
from app.ingest.adapters.stt_openai import OpenAISttAdapter


@dataclass(frozen=True, slots=True)
class AdapterContext:
    """Всё, что нужно адаптеру одного вызова: расшифрованный ключ и настройки сети."""

    api_key: str
    base_url: str | None = None
    model: str | None = None
    credential_id: UUID | None = None
    transport: httpx.AsyncBaseTransport | None = None
    client_factory: AdapterClientFactory | None = None
    allowed_private_hosts: tuple[str, ...] = ()
    timeout_sec: float = 120.0


type AdapterFactory = Callable[[AdapterContext], CapabilityAdapter]


@dataclass(frozen=True, slots=True)
class AdapterSpec:
    """Одна пара «возможность + провайдер» с подписью для настроек."""

    capability: Capability
    provider: str
    label: str
    factory: AdapterFactory


@dataclass(slots=True)
class AdapterRegistry:
    """Поддержанные провайдеры возможностей. Ошибка конфигурации — `ValueError`."""

    _specs: dict[tuple[Capability, str], AdapterSpec] = field(default_factory=dict)

    def register(self, spec: AdapterSpec) -> None:
        key = (spec.capability, spec.provider)
        if key in self._specs:
            raise ValueError(f"Адаптер {spec.capability}/{spec.provider} уже зарегистрирован")
        self._specs[key] = spec

    def supports(self, capability: Capability, provider: str) -> bool:
        return (capability, provider) in self._specs

    def providers(self, capability: Capability) -> list[tuple[str, str]]:
        """Подписанные провайдеры возможности: (идентификатор, подпись для интерфейса)."""
        return [
            (spec.provider, spec.label)
            for (item, _), spec in self._specs.items()
            if item is capability
        ]

    def create(
        self, capability: Capability, provider: str, context: AdapterContext
    ) -> CapabilityAdapter:
        spec = self._specs.get((capability, provider))
        if spec is None:
            raise CapabilityError(
                ErrorClass.UNSUPPORTED,
                f"Провайдер «{provider}» не умеет эту задачу. Выберите другого провайдера в "
                "настройках",
            )
        return spec.factory(context)


def register_stt_providers(registry: AdapterRegistry) -> None:
    """Провайдеры распознавания речи: Deepgram, OpenAI, Groq, OpenAI-совместимый сервер."""

    def deepgram(context: AdapterContext) -> CapabilityAdapter:
        return DeepgramSttAdapter(
            context.api_key,
            model=context.model,
            transport=context.transport,
            client_factory=context.client_factory,
            timeout_sec=context.timeout_sec,
            credential_id=context.credential_id,
        )

    def openai_compatible(context: AdapterContext) -> CapabilityAdapter:
        return OpenAISttAdapter(
            "openai_compatible",
            context.api_key,
            base_url=context.base_url,
            model=context.model,
            transport=context.transport,
            client_factory=context.client_factory,
            timeout_sec=context.timeout_sec,
            credential_id=context.credential_id,
        )

    def named(provider: str):
        def build(context: AdapterContext) -> CapabilityAdapter:
            return OpenAISttAdapter(
                provider,
                context.api_key,
                model=context.model,
                transport=context.transport,
                client_factory=context.client_factory,
                timeout_sec=context.timeout_sec,
                credential_id=context.credential_id,
            )

        return build

    registry.register(AdapterSpec(Capability.SPEECH_TO_TEXT, "deepgram", "Deepgram", deepgram))
    registry.register(
        AdapterSpec(Capability.SPEECH_TO_TEXT, "openai", "OpenAI Whisper", named("openai"))
    )
    registry.register(AdapterSpec(Capability.SPEECH_TO_TEXT, "groq", "Groq Whisper", named("groq")))
    registry.register(
        AdapterSpec(
            Capability.SPEECH_TO_TEXT,
            "openai_compatible",
            "Совместимый с OpenAI сервер",
            openai_compatible,
        )
    )


def register_ocr_providers(registry: AdapterRegistry) -> None:
    """Контракты внешних OCR-провайдеров (RFC-0006, шаг 4).

    Вызовы не реализованы: страницы-сканы в волне 3 распознаёт модель с чтением PDF. Ключ
    Mistral/Yandex можно сохранить заранее — провайдер появится в настройках возможности.
    """

    def factory(provider: str):
        def build(context: AdapterContext) -> CapabilityAdapter:
            return ContractOcrAdapter(provider=provider, credential_id=context.credential_id)

        return build

    for provider, label in OCR_PROVIDERS:
        registry.register(AdapterSpec(Capability.OCR, provider, label, factory(provider)))


def build_default_registry(extra: Iterable[AdapterSpec] = ()) -> AdapterRegistry:
    """Реестр по умолчанию: ключи по типам задач, которые уже поддержаны."""
    registry = AdapterRegistry()
    for spec in extra:
        registry.register(spec)
    register_stt_providers(registry)
    register_ocr_providers(registry)
    return registry
