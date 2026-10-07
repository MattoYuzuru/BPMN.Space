"""Примеры процессов и расшифровка голоса — сценарии без хранения состояния."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.fixtures import read_text
from app.fixtures.types import Example
from app.ingest.stt import NoSpeechError, SpeechToText, Transcript
from app.services.common import too_large
from app.services.errors import InvalidInputError, SpeechNotRecognizedError, UnsupportedMediaError

_AUDIO_CONTAINERS = {"video/webm", "video/ogg", "application/ogg", "application/octet-stream"}


@dataclass(frozen=True, slots=True, kw_only=True)
class ExampleView:
    id: str
    title: str
    description: str
    content: str


class ExampleService:
    def __init__(self, examples: Sequence[Example]) -> None:
        self._examples = examples

    def list(self) -> list[ExampleView]:
        return [
            ExampleView(
                id=e.id, title=e.title, description=e.description, content=read_text(e.text)
            )
            for e in self._examples
        ]


class TranscriptionService:
    def __init__(self, stt: SpeechToText, *, max_audio_bytes: int) -> None:
        self._stt = stt
        self._max_bytes = max_audio_bytes

    async def transcribe(self, data: bytes, *, mime: str | None) -> Transcript:
        base_mime = (mime or "application/octet-stream").split(";")[0].strip().lower()
        if not base_mime.startswith("audio/") and base_mime not in _AUDIO_CONTAINERS:
            raise UnsupportedMediaError("Это не аудиозапись. Поддерживаются webm, ogg, wav, mp3")
        if not data:
            raise InvalidInputError("Аудиозапись пустая")
        if len(data) > self._max_bytes:
            raise too_large("Запись", self._max_bytes)
        try:
            transcript = await self._stt.transcribe(data, mime=base_mime)
        except NoSpeechError:
            raise SpeechNotRecognizedError from None
        if not transcript.text.strip():
            raise SpeechNotRecognizedError
        return transcript
