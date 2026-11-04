"""Примеры процессов и расшифровка голоса — сценарии без хранения состояния."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from uuid import UUID

from app.domain.capabilities import CapabilityUnavailableError
from app.fixtures import read_text
from app.fixtures.types import Example
from app.ingest.stt import NoSpeechError, SpeechToText, Transcript
from app.services.common import too_large
from app.services.errors import (
    InvalidInputError,
    SpeechNotRecognizedError,
    ToolUnavailableError,
    UnsupportedMediaError,
)

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
    def __init__(
        self,
        stt: SpeechToText,
        *,
        max_audio_bytes: int,
        stt_for_user: Callable[[UUID | None], SpeechToText] | None = None,
    ) -> None:
        self._stt = stt
        self._max_bytes = max_audio_bytes
        # Ключи вызывающего пользователя (RFC-0006); None — сразу серверный провайдер.
        self._stt_for_user = stt_for_user

    def _engine(self, user_id: UUID | None) -> SpeechToText:
        return self._stt_for_user(user_id) if self._stt_for_user is not None else self._stt

    async def transcribe(
        self, data: bytes, *, mime: str | None, user_id: UUID | None = None
    ) -> Transcript:
        """Расшифровка голосовой заметки; у вошедшего пользователя — на его ключах."""
        base_mime = (mime or "application/octet-stream").split(";")[0].strip().lower()
        if not base_mime.startswith("audio/") and base_mime not in _AUDIO_CONTAINERS:
            raise UnsupportedMediaError("Это не аудиозапись. Поддерживаются webm, ogg, wav, mp3")
        if not data:
            raise InvalidInputError("Аудиозапись пустая")
        if len(data) > self._max_bytes:
            raise too_large("Запись", self._max_bytes)
        try:
            transcript = await self._engine(user_id).transcribe(data, mime=base_mime)
        except NoSpeechError:
            raise SpeechNotRecognizedError from None
        except CapabilityUnavailableError as error:
            outcome = error.outcome
            raise ToolUnavailableError(
                outcome.message or "Распознавание речи недоступно",
                reason=outcome.reason,
                done=outcome.done,
                remaining=outcome.remaining,
                alternatives=outcome.alternatives,
            ) from None
        if not transcript.text.strip():
            raise SpeechNotRecognizedError
        return transcript
