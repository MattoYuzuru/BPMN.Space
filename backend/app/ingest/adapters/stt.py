"""Распознавание речи: общий контракт STT-адаптеров возможности (RFC-0006).

Адаптер возможности `speech_to_text` — обычный `SpeechToText` (его ждёт `MediaTranscriber`)
плюс метаданные маршрутизации: провайдер, модель и id ключа для `derivation` и настроек.
"""

from typing import Protocol

from app.domain.capabilities import Capability
from app.ingest.adapters.base import CapabilityAdapter
from app.ingest.stt import SpeechToText


class SttAdapter(CapabilityAdapter, SpeechToText, Protocol):
    """Провайдер распознавания речи: `transcribe` и дешёвая проверка ключа."""

    capability: Capability


__all__ = ["SttAdapter"]
