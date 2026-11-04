"""Распознавание речи (RFC §5.2): голосовая заметка → текст для правки аналитиком.

Mock: ждёт `mock_transcription_delay_sec` и возвращает примерную, заранее заготовленную
расшифровку на тему энергетики (выбор детерминирован по содержимому файла), а не распознаёт
загруженный звук; длительность оценивается по размеру.
Боевые адаптеры живут в `ingest/adapters/` (RFC-0006): Deepgram и OpenAI-совместимый провайдер
(OpenAI, Groq), выбор — маршрутизатор по ключам пользователя. Длинные файлы и видео режет на
сегменты `media.py` (ffmpeg).
TODO(real): #6 RFC §5.2 предполагает Yandex SpeechKit: `ffmpeg` перепаковывает webm/opus в
OGG_OPUS mono; запись ≤ 30 с и ≤ 1 МБ — STT v1 синхронно, длиннее — v3 `recognizeFileAsync` +
опрос `getRecognition`. Адаптеры не делают асинхронную обработку: длинные записи режет `media.py`.
"""

import asyncio
import hashlib
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

_OPUS_BYTES_PER_SECOND = 4000  # ~32 кбит/с — типичный битрейт записи MediaRecorder
_MAX_ESTIMATE_SEC = 3600.0


@dataclass(frozen=True, slots=True, kw_only=True)
class TimedText:
    """Реплика с временем начала от начала записи (секунды)."""

    start_sec: float
    text: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Transcript:
    """Расшифровка сегмента или записи; метаданные — для `derivation` и оценки стоимости."""

    text: str
    duration_sec: float
    language: str = "ru-RU"
    # Реплики с таймкодами, если провайдер их вернул; нужны для `[мм:сс]` в длинных записях.
    utterances: tuple[TimedText, ...] = ()
    provider: str | None = None  # кто ответил: `deepgram`, `openai`, `groq`, `mock`…
    model: str | None = None  # модель провайдера, если известна
    cost_usd: float | None = None  # None — провайдер стоимость не сообщает
    credential_id: UUID | None = None  # ключ пользователя, которым оплачен вызов


class NoSpeechError(Exception):
    """Провайдер обработал запись, но не нашёл распознаваемой речи."""


class SpeechToText(Protocol):
    async def transcribe(self, data: bytes, *, mime: str | None) -> Transcript: ...


_SAMPLES = (
    "Записываю по итогам планёрки. Заявку на вывод линии в ремонт готовит служба линий, "
    "диспетчерский центр смотрит её за семь рабочих дней. Если режим не позволяет, "
    "приходит отказ с причинами, и мы переносим ремонт в следующий месяц.",
    "Уточнение по техприсоединению. Проверку комплектности делает группа приёма заявок, "
    "уведомление уходит заявителю через личный кабинет. Счёт выставляет финансовый отдел "
    "после того, как заявитель принял условия договора.",
    "По наряду-допуску: допускающий сначала проверяет рабочее место, потом проводит целевой "
    "инструктаж. Если есть замечания, бригаду не допускаем, пока их не устранят.",
)


class MockSpeechToText:
    def __init__(self, *, delay_sec: float) -> None:
        self._delay_sec = delay_sec

    async def transcribe(self, data: bytes, *, mime: str | None) -> Transcript:  # noqa: ARG002
        await asyncio.sleep(self._delay_sec)
        digest = hashlib.sha256(data).digest()
        duration = min(max(len(data) / _OPUS_BYTES_PER_SECOND, 1.0), _MAX_ESTIMATE_SEC)
        return Transcript(
            text=_SAMPLES[digest[0] % len(_SAMPLES)],
            duration_sec=round(duration, 1),
        )
