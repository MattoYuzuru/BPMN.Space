"""Заготовка адаптера `tts` (RFC-0006, шаг 1): только контракт, низкий приоритет.

Озвучка вопросов для интервью и аудиорезюме; реализация — после основных инструментов.
"""

from dataclasses import dataclass

from app.domain.capabilities import Capability
from app.ingest.adapters.base import CapabilityAdapter
from app.ingest.adapters.vision import not_implemented


@dataclass(frozen=True, slots=True, kw_only=True)
class SpeechRequest:
    """Текст для озвучки и необязательный голос провайдера."""

    text: str
    voice: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioClip:
    """Готовый аудиофайл (ogg/opus или mp3) и его MIME."""

    data: bytes
    mime: str


class TtsAdapter(CapabilityAdapter):
    """`speak(text, voice?)` — возможность `tts`."""

    capability = Capability.TTS

    async def speak(self, request: SpeechRequest) -> AudioClip:
        del request
        raise not_implemented()
