"""Оценка обработки записи до загрузки (RFC-0006, «Видео»).

Перед платной обработкой аналитик видит, что именно будет сделано: минуты распознавания речи,
число кадров и ориентировочную цену по каталогу. Оценка ничего не запускает и не ходит в сеть:
минуты считаются по длительности файла, кадры — по профилю обработки, цена — по датированному
каталогу цен (STT по минутам, vision по цене изображений у моделей из справочника `llm`).

Диапазон честный: провайдеры и модели разные, поэтому минимум — самый дешёвый сценарий,
максимум — самый дорогой из поддержанных. Точную цену даёт только фактический вызов; в
`derivation.cost_usd` производного узла попадает она.
"""

import math
from dataclasses import dataclass
from datetime import date

from app.ingest.frames import FRAME_PROFILES, MediaProfile, profile_label
from app.ingest.frames import media_profile as parse_media_profile
from app.llm.capabilities import ANTHROPIC_CATALOG

# Цены распознавания речи в долларах за минуту; проверены по каталогу провайдеров 2026-11-04
# (`docs/research/tool-providers-2026-11.md`). Deepgram Nova-3, Groq Whisper, ElevenLabs Scribe,
# OpenAI Whisper: диаризация и надбавки не учитываются — оценка «от и до».
STT_PRICES_CHECKED_ON = date(2026, 11, 4)
STT_USD_PER_MINUTE: tuple[tuple[str, str, float], ...] = (
    ("deepgram", "Deepgram Nova-3", 0.0077),
    ("groq", "Groq Whisper", 0.04 / 60),
    ("elevenlabs", "ElevenLabs Scribe", 0.22 / 60),
    ("openai", "OpenAI Whisper", 0.006),
)

# Сколько токенов примерно занимает один кадр у vision-модели: изображение и короткий ответ.
VISION_INPUT_TOKENS_PER_FRAME = 500
VISION_OUTPUT_TOKENS_PER_FRAME = 200
# Сводка — один запрос по началу записи: оценка входа/выхода (она не основание, а навигация).
SUMMARY_INPUT_TOKENS = 4_000
SUMMARY_OUTPUT_TOKENS = 800
# Ориентировочные цены OpenAI за 1 млн токенов (вход, выход) на 2026-11: в справочнике моделей
# цен OpenAI пока нет, поэтому диапазон оценён по публичному прайсу gpt-4o/mini и gpt-5.
OPENAI_VISION_PRICES: tuple[tuple[float, float], ...] = (
    (0.15, 0.60),  # gpt-4o-mini
    (1.25, 10.0),  # gpt-5
    (2.00, 8.00),  # gpt-4.1
    (2.50, 10.0),  # gpt-4o
)
# Ожидаемые смены сцены в минуту для нижней/верхней границы числа кадров, если профиль
# не задаёт их явно: реальное число зависит от записи, поэтому диапазон широкий.
SCENE_CHANGES_PER_MINUTE = 3.0


@dataclass(frozen=True, slots=True)
class MoneyRange:
    min_usd: float | None
    max_usd: float | None


@dataclass(frozen=True, slots=True)
class MediaEstimate:
    """Оценка обработки: минуты STT, кадры/запросы vision и цена по каталогу."""

    duration_sec: float
    media_profile: str
    profile_label: str
    stt_minutes: float
    stt_cost: MoneyRange
    frames_min: int
    frames_max: int
    vision_requests: int
    vision_cost: MoneyRange
    summary_cost: MoneyRange
    total_cost: MoneyRange
    priced_on: date
    note: str


def _vision_prices() -> tuple[float, float, float, float]:
    """Цены 1 млн токенов: (вход min, выход min, вход max, выход max) по vision-моделям.

    Диапазон объединяет справочник Claude и ориентировочные цены OpenAI: ключ пользователя
    может оказаться любым из поддержанных, а оценка должна покрывать все варианты.
    """
    pairs = [
        (entry.prices.input, entry.prices.output)
        for entry in ANTHROPIC_CATALOG.values()
        if entry.vision and entry.prices is not None
    ]
    pairs.extend(OPENAI_VISION_PRICES)
    if not pairs:
        return 0.0, 0.0, 0.0, 0.0
    return (
        min(input_price for input_price, _ in pairs),
        min(output_price for _, output_price in pairs),
        max(input_price for input_price, _ in pairs),
        max(output_price for _, output_price in pairs),
    )


def _frame_bounds(
    duration_sec: float, profile: MediaProfile, *, frame_max_cap: int
) -> tuple[int, int]:
    """Нижняя и верхняя границы числа кадров: периодические кадры + возможные смены сцены.

    Верхний предел — и профиль, и серверная настройка `MEDIA_FRAME_MAX_FRAMES`: обработка
    никогда не сохранит больше кадров, чем разрешает сервер.
    """
    if profile is MediaProfile.AUDIO:
        return 0, 0
    frames = FRAME_PROFILES[profile]
    limit = min(frames.max_frames, max(frame_max_cap, 1))
    periodic = int(duration_sec // frames.min_interval_sec) + 1
    scenes = math.ceil(duration_sec / 60.0 * SCENE_CHANGES_PER_MINUTE)
    low = min(periodic, limit)
    high = min(periodic + scenes, limit)
    return low, max(high, low)


def estimate_media(
    *,
    duration_sec: float,
    media_profile: str | None,
    has_video: bool,
    vision_batch_size: int = 4,
    frame_max_cap: int = 600,
) -> MediaEstimate:
    """Оценка по длительности и профилю; не обращается к сети и не создаёт записей в БД."""
    profile = _profile(media_profile)
    label = profile_label(profile.value) or "Только звук"
    minutes = max(duration_sec, 0.0) / 60.0
    stt_min = round(minutes * min(price for _, _, price in STT_USD_PER_MINUTE), 6)
    stt_max = round(minutes * max(price for _, _, price in STT_USD_PER_MINUTE), 6)
    frames_min, frames_max = _frame_bounds(duration_sec, profile, frame_max_cap=frame_max_cap)
    if not has_video:
        frames_min = frames_max = 0
    batch = max(vision_batch_size, 1)
    requests = math.ceil(frames_max / batch) if frames_max else 0
    input_min, output_min, input_max, output_max = _vision_prices()
    per_frame_min = (
        VISION_INPUT_TOKENS_PER_FRAME * input_min + VISION_OUTPUT_TOKENS_PER_FRAME * output_min
    ) / 1_000_000
    per_frame_max = (
        VISION_INPUT_TOKENS_PER_FRAME * input_max + VISION_OUTPUT_TOKENS_PER_FRAME * output_max
    ) / 1_000_000
    vision_min = round(frames_min * per_frame_min, 6)
    vision_max = round(frames_max * per_frame_max, 6)
    # Краткое содержание создаётся только для видео с кадрами (профили sparse/detailed).
    if frames_max:
        summary_min = round(
            (SUMMARY_INPUT_TOKENS * input_min + SUMMARY_OUTPUT_TOKENS * output_min) / 1_000_000,
            6,
        )
        summary_max = round(
            (SUMMARY_INPUT_TOKENS * input_max + SUMMARY_OUTPUT_TOKENS * output_max) / 1_000_000,
            6,
        )
    else:
        summary_min = summary_max = 0.0
    return MediaEstimate(
        duration_sec=round(duration_sec, 3),
        media_profile=profile.value,
        profile_label=label,
        stt_minutes=round(minutes, 2),
        stt_cost=MoneyRange(stt_min, stt_max),
        frames_min=frames_min,
        frames_max=frames_max,
        vision_requests=requests,
        vision_cost=MoneyRange(vision_min, vision_max),
        summary_cost=MoneyRange(summary_min, summary_max),
        total_cost=MoneyRange(
            round(stt_min + vision_min + summary_min, 6),
            round(stt_max + vision_max + summary_max, 6),
        ),
        priced_on=STT_PRICES_CHECKED_ON,
        note=(
            "Ориентировочно по каталогу цен: фактическая стоимость зависит от подключённых ключей "
            "и выбранной модели. Кадры ограничены профилем обработки и отбрасываются по "
            "перцептивному хешу, поэтому реальное число обычно меньше верхней границы."
        ),
    )


def _profile(name: str | None) -> MediaProfile:
    try:
        profile = parse_media_profile(name)
    except ValueError:
        profile = MediaProfile.AUDIO
    return profile or MediaProfile.AUDIO
