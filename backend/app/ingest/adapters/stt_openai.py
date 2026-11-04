"""OpenAI-совместимое распознавание речи: OpenAI, Groq и любой сервер с `/audio/transcriptions`.

Groq и OpenAI отвечают Whisper-моделью; адрес OpenAI и Groq фиксирован, у совместимого сервера
его задаёт пользователь (тогда работает защита от SSRF и закрепление IP). Текст и длительность
берутся из `verbose_json`; таймкоды реплик не запрашиваются — сегменты и так по 10 минут.
"""

import json

import httpx

from app.domain.capabilities import Capability, CapabilityError, ErrorClass
from app.ingest.adapters.http import HTTP_ERROR_STATUS, provider_client, provider_error
from app.ingest.stt import NoSpeechError, Transcript

OPENAI_BASE_URL = "https://api.openai.com/v1"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
OPENAI_MODEL = "whisper-1"
GROQ_MODEL = "whisper-large-v3-turbo"

# Провайдер → (адрес по умолчанию, модель по умолчанию, подпись для сообщений).
_PROVIDERS = {
    "openai": (OPENAI_BASE_URL, OPENAI_MODEL, "OpenAI"),
    "groq": (GROQ_BASE_URL, GROQ_MODEL, "Groq"),
    "openai_compatible": (None, OPENAI_MODEL, "Провайдер распознавания"),
}


class OpenAISttAdapter:
    """`POST {base_url}/audio/transcriptions` (multipart), модель Whisper."""

    capability = Capability.SPEECH_TO_TEXT

    def __init__(
        self,
        provider: str,
        api_key: str,
        *,
        base_url: str | None = None,
        model: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        client_factory=None,
        timeout_sec: float = 120.0,
        credential_id=None,
    ) -> None:
        if provider not in _PROVIDERS:
            raise ValueError(f"Неизвестный провайдер распознавания: {provider}")
        default_url, default_model, label = _PROVIDERS[provider]
        url = default_url or base_url
        if not url:
            raise ValueError("Для совместимого провайдера нужен адрес API")
        self.provider = provider
        self.model: str | None = model or default_model
        self.credential_id = credential_id
        self._label = label
        self._key = api_key
        self._http = provider_client(
            base_url=url,
            timeout_sec=timeout_sec,
            transport=transport,
            guard_host=default_url is None,
            client_factory=client_factory,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def check(self) -> str:
        """Список моделей: доступность ключа без оплаты распознавания."""
        try:
            response = await self._http.get(
                "/models", headers={"Authorization": f"Bearer {self._key}"}
            )
        except httpx.HTTPError:
            raise CapabilityError(
                ErrorClass.TRANSIENT, f"{self._label} временно недоступен: повторите позже"
            ) from None
        if response.status_code >= HTTP_ERROR_STATUS:
            raise await provider_error(response, provider_label=self._label)
        return f"Ключ {self._label} действует"

    async def transcribe(self, data: bytes, *, mime: str | None) -> Transcript:
        files = {
            "file": ("segment.ogg", data, mime or "application/octet-stream"),
        }
        form = {
            "model": self.model,
            "language": "ru",
            "response_format": "verbose_json",
        }
        try:
            response = await self._http.post(
                "/audio/transcriptions",
                files=files,
                data=form,
                headers={"Authorization": f"Bearer {self._key}"},
            )
        except (httpx.TimeoutException, httpx.TransportError):
            raise CapabilityError(
                ErrorClass.TRANSIENT, f"{self._label} временно недоступен: повторите позже"
            ) from None
        if response.status_code >= HTTP_ERROR_STATUS:
            raise await provider_error(response, provider_label=self._label)
        try:
            payload = response.json()
            text = str(payload.get("text", "")).strip()
            duration = float(payload.get("duration") or 0.0)
        except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
            raise CapabilityError(
                ErrorClass.TRANSIENT, f"{self._label} вернул ответ в неизвестном формате"
            ) from None
        if not text:
            raise NoSpeechError
        return Transcript(
            text=text,
            duration_sec=max(0.0, duration),
            language=str(payload.get("language") or "ru"),
            provider=self.provider,
            model=self.model,
        )
