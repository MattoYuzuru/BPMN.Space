"""Серверный адаптер Deepgram для расшифровки аудио."""

import asyncio
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.ingest.stt import NoSpeechError, TimedText, Transcript

DEEPGRAM_MODEL = "nova-3"


class DeepgramSpeechToText:
    def __init__(self, api_key: str, *, timeout_sec: float = 120) -> None:
        self._api_key = api_key
        self._timeout_sec = timeout_sec

    async def transcribe(self, data: bytes, *, mime: str | None) -> Transcript:
        return await asyncio.to_thread(self._transcribe_sync, data, mime)

    def _transcribe_sync(self, data: bytes, mime: str | None) -> Transcript:
        query = urlencode(
            {
                "model": DEEPGRAM_MODEL,
                "language": "ru",
                "smart_format": "true",
                "utterances": "true",
            }
        )
        request = Request(
            f"https://api.deepgram.com/v1/listen?{query}",
            data=data,
            headers={
                "Authorization": f"Token {self._api_key}",
                "Content-Type": mime or "application/octet-stream",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout_sec) as response:  # noqa: S310
                result = json.loads(response.read())
        except HTTPError as error:
            # Не возвращаем тело: оно может содержать данные запроса или ответ провайдера.
            raise RuntimeError(f"Deepgram завершил запрос с HTTP {error.code}") from None
        except (URLError, TimeoutError, json.JSONDecodeError):
            raise RuntimeError("Не удалось получить расшифровку от Deepgram") from None

        try:
            alternative = result["results"]["channels"][0]["alternatives"][0]
            raw_text = alternative["transcript"]
            if not isinstance(raw_text, str):
                raise TypeError
            text = raw_text.strip()
            duration = float(result["metadata"].get("duration", 0))
        except (KeyError, IndexError, TypeError, ValueError):
            raise RuntimeError("Deepgram вернул ответ в неизвестном формате") from None
        if not text:
            raise NoSpeechError
        return Transcript(
            text=text,
            duration_sec=max(0.0, duration),
            language="ru-RU",
            utterances=_utterances(result),
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
