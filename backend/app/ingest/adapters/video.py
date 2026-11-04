"""Заготовка адаптера `video_understanding` (RFC-0006, шаг 1): только контракт.

Видео целиком умеет Gemini; без отдельного ключа работают кадры через ffmpeg + `vision`.
Реализация — волна 3, вместе с профилями обработки и общей лентой «речь + экран».
"""

from dataclasses import dataclass

from app.domain.capabilities import Capability
from app.ingest.adapters.base import CapabilityAdapter
from app.ingest.adapters.vision import not_implemented


@dataclass(frozen=True, slots=True, kw_only=True)
class VideoRequest:
    """Видео для `analyze_video`: файл или диапазон уже нарезанных кадров."""

    data: bytes
    mime: str
    question: str
    range_start_sec: float | None = None
    range_end_sec: float | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class VideoEvent:
    """Событие видео с таймкодом — основание с пометкой «по изображению»."""

    start_sec: float
    end_sec: float | None
    description: str


class VideoAdapter(CapabilityAdapter):
    """`analyze_video(media_id, question, range?)` — возможность `video_understanding`."""

    capability = Capability.VIDEO_UNDERSTANDING

    async def analyze_video(self, video: VideoRequest) -> tuple[VideoEvent, ...]:
        del video
        raise not_implemented()
