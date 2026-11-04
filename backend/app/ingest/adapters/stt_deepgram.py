"""Deepgram: распознавание речи по ключу пользователя (перенос из `ingest/deepgram.py`).

Один синхронный HTTP-запрос на запись или сегмент; длинные файлы режет `media.py`. Ошибки
классифицируются по RFC-0006: `auth` (401/403), `quota_exhausted` (402/признак квоты),
`transient` (408/429/5xx/таймаут), `unsupported` (413/415/422), `fatal` — остальное.
"""

import json

import httpx

from app.domain.capabilities import Capability, CapabilityError, ErrorClass
from app.ingest.adapters.http import HTTP_ERROR_STATUS, provider_client, provider_error
from app.ingest.stt import NoSpeechError, TimedText, Transcript

DEEPGRAM_MODEL = "nova-3"
DEEPGRAM_BASE_URL = "https://api.deepgram.com"
_PROVIDER_LABEL = "Deepgram"


class DeepgramSttAdapter:
    """Ключ Deepgram: `provider=deepgram`, модель `nova-3`, таймкоды и говорящие."""

    capability = Capability.SPEECH_TO_TEXT
    provider = "deepgram"

    def __init__(
        self,
        api_key: str,
        *,
        model: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        client_factory=None,
        timeout_sec: float = 120.0,
        credential_id=None,
    ) -> None:
        self._api_key = api_key
        self.model: str | None = model or DEEPGRAM_MODEL
        self.credential_id = credential_id
        self._http = provider_client(
            base_url=DEEPGRAM_BASE_URL,
            timeout_sec=timeout_sec,
            transport=transport,
            client_factory=client_factory,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def check(self) -> str:
        """`GET /v1/auth/token` — дешёвая проверка ключа без оплаты распознавания."""
        try:
            response = await self._http.get(
                "/v1/auth/token", headers={"Authorization": f"Token {self._api_key}"}
            )
        except httpx.HTTPError:
            raise CapabilityError(
                ErrorClass.TRANSIENT, "Deepgram временно недоступен: повторите позже"
            ) from None
        except ValueError as error:
            raise CapabilityError(
                ErrorClass.UNSUPPORTED,
                f"Адрес провайдера отклонён проверкой безопасности: {error}",
            ) from None
        if response.status_code >= HTTP_ERROR_STATUS:
            raise await provider_error(response, provider_label=_PROVIDER_LABEL)
        return "Ключ Deepgram действует"

    async def transcribe(self, data: bytes, *, mime: str | None) -> Transcript:
        params = {
            "model": self.model,
            "language": "ru",
            "smart_format": "true",
            "utterances": "true",
        }
        headers = {
            "Authorization": f"Token {self._api_key}",
            "Content-Type": mime or "application/octet-stream",
        }
        try:
            response = await self._http.post(
                "/v1/listen", params=params, content=data, headers=headers
            )
        except (httpx.TimeoutException, httpx.TransportError):
            raise CapabilityError(
                ErrorClass.TRANSIENT, "Deepgram временно недоступен: повторите позже"
            ) from None
        except ValueError as error:
            raise CapabilityError(
                ErrorClass.UNSUPPORTED,
                f"Адрес провайдера отклонён проверкой безопасности: {error}",
            ) from None
        if response.status_code >= HTTP_ERROR_STATUS:
            raise await provider_error(response, provider_label=_PROVIDER_LABEL)
        try:
            result = response.json()
        except json.JSONDecodeError:
            raise CapabilityError(
                ErrorClass.TRANSIENT, "Deepgram вернул ответ в неизвестном формате"
            ) from None
        try:
            alternative = result["results"]["channels"][0]["alternatives"][0]
            raw_text = alternative["transcript"]
            if not isinstance(raw_text, str):
                raise TypeError
            text = raw_text.strip()
            duration = float(result["metadata"].get("duration", 0))
        except (KeyError, IndexError, TypeError, ValueError):
            raise CapabilityError(
                ErrorClass.TRANSIENT, "Deepgram вернул ответ в неизвестном формате"
            ) from None
        if not text:
            raise NoSpeechError
        return Transcript(
            text=text,
            duration_sec=max(0.0, duration),
            language="ru-RU",
            utterances=_utterances(result),
            provider=self.provider,
            model=self.model,
            credential_id=self.credential_id,
        )


def _utterances(result: dict) -> tuple[TimedText, ...]:
    """Реплики с таймкодами; отсутствующее или кривое поле просто даёт пустой результат."""
    try:
        items = result["results"]["utterances"]
        return tuple(
            TimedText(start_sec=max(0.0, float(item["start"])), text=item["transcript"].strip())
            for item in items
            if isinstance(item["transcript"], str) and item["transcript"].strip()
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        return ()
