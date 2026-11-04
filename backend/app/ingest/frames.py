"""Ключевые кадры видео (RFC-0006, «Видео»): смена сцены и кадр не реже N секунд.

ffmpeg делает два прохода: кадры смены сцены (`select='gt(scene,T)'`) и периодические кадры
(`fps=1/N`). Кадры уменьшаются до ширины профиля и сохраняются JPEG. Почти одинаковые кадры
отбрасываются перцептивным dhash: ffmpeg отдаёт каждый кадр как rawvideo gray 16×16, а
приложение сравнивает соседние пиксели строк и считает расстояние Хэмминга. Pillow не нужен:
на VPS остаются только ffmpeg/ffprobe, как и записано в RFC-0006.

Временная папка удаляется всегда, даже при ошибке и отмене. Если кадров нет (нет видеопотока
или ffmpeg недоступен), вызывающий код оставляет расшифровку и предупреждение, а не роняет
запись: звук — главный источник, кадры — дополнение.
"""

import asyncio
import logging
import re
import shutil
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from app.ingest.media import INPUT_GUARD, MediaError

logger = logging.getLogger(__name__)

_STDERR_LOG_LIMIT = 2000
_PTS = re.compile(r"pts_time:([0-9]+(?:\.[0-9]+)?)")
_HASH_SIDE = 16
_HASH_BYTES = _HASH_SIDE * _HASH_SIDE
_FRAME_QUALITY = 3
# Два кадра ближе этого интервала — один и тот же момент (сцена и периодический кадр совпали).
_MIN_FRAME_GAP_SEC = 0.5


class MediaProfile(StrEnum):
    """Профиль обработки записи (RFC-0006, «Видео»): от него зависит объём платной работы."""

    AUDIO = "audio"
    SPARSE = "sparse"
    DETAILED = "detailed"


@dataclass(frozen=True, slots=True)
class FrameProfile:
    """Порог смены сцены, шаг периодического кадра и предел числа кадров."""

    media_profile: MediaProfile
    label: str
    scene_threshold: float
    min_interval_sec: float
    max_frames: int

    @property
    def description(self) -> str:
        return (
            f"смена сцены > {self.scene_threshold:g}, кадр не реже "
            f"{self.min_interval_sec:g} с, до {self.max_frames} кадров"
        )


FRAME_PROFILES: dict[MediaProfile, FrameProfile] = {
    MediaProfile.SPARSE: FrameProfile(
        media_profile=MediaProfile.SPARSE,
        label="Звук + редкие кадры",
        scene_threshold=0.35,
        min_interval_sec=90.0,
        max_frames=120,
    ),
    MediaProfile.DETAILED: FrameProfile(
        media_profile=MediaProfile.DETAILED,
        label="Подробно: звук + частые кадры",
        scene_threshold=0.20,
        min_interval_sec=20.0,
        max_frames=600,
    ),
}


def media_profile(name: str | None) -> MediaProfile | None:
    """Разбор профиля из запроса; `None`/`audio` — только звук, кадры не извлекаются."""
    if name is None or not name.strip():
        return MediaProfile.AUDIO
    try:
        return MediaProfile(name.strip().lower())
    except ValueError:
        allowed = ", ".join(profile.value for profile in MediaProfile)
        raise ValueError(f"Неизвестный профиль обработки записи. Доступно: {allowed}") from None


def frame_profile(name: str | None) -> FrameProfile | None:
    """Профиль кадров; `None` — профиль «только звук»."""
    profile = media_profile(name)
    if profile is None or profile is MediaProfile.AUDIO:
        return None
    return FRAME_PROFILES[profile]


def profile_label(name: str | None) -> str | None:
    profile = media_profile(name)
    if profile is None:
        return None
    if profile is MediaProfile.AUDIO:
        return "Только звук"
    return FRAME_PROFILES[profile].label


def format_timecode(seconds: float) -> str:
    total = max(int(seconds), 0)
    return f"[{total // 60:02d}:{total % 60:02d}]"


@dataclass(frozen=True, slots=True)
class FrameCandidate:
    """Кадр на диске до дедупликации: путь и время в записи."""

    at_sec: float
    path: Path


@dataclass(frozen=True, slots=True)
class ExtractedFrame:
    """Готовый кадр: номер по порядку, время в записи и JPEG-байты для хранилища."""

    index: int
    at_sec: float
    data: bytes


class FrameExtractionError(MediaError):
    """Кадры не извлечены; расшифровка при этом может остаться готовой."""


class FrameExtractor:
    """ffmpeg + dhash: сцены, периодические кадры и дедупликация без Pillow."""

    def __init__(
        self,
        *,
        ffmpeg: str = "ffmpeg",
        timeout_sec: float = 900.0,
        frame_width: int = 768,
        dedup_bits: int = 8,
        max_frames_cap: int = 600,
    ) -> None:
        self._ffmpeg = ffmpeg
        self._timeout = timeout_sec
        self._width = max(frame_width, 64)
        self._dedup_bits = max(dedup_bits, 0)
        self._max_frames = max(max_frames_cap, 1)
        self._last_stderr = ""

    @property
    def available(self) -> bool:
        return shutil.which(self._ffmpeg) is not None

    @property
    def width(self) -> int:
        """Ширина сохранённого кадра: записывается в `derivation.params`."""
        return self._width

    async def extract(self, source: Path, profile: FrameProfile) -> list[ExtractedFrame]:
        """Кадры записи по профилю; порядок — по времени, номера с 1."""
        if not self.available:
            raise FrameExtractionError("На сервере недоступен ffmpeg: кадры не извлечены")
        workdir = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="frames-"))
        try:
            # Проходы независимы: сбой одного (битый фрагмент, фильтр) не отменяет другой.
            scene = await self._safe_candidates(source, workdir / "scene", profile, mode="scene")
            periodic = await self._safe_candidates(
                source, workdir / "interval", profile, mode="interval"
            )
            candidates = sorted([*scene, *periodic], key=lambda item: item.at_sec)
            if not candidates:
                # Короткая запись или статичный экран: хотя бы первый кадр, иначе описать нечего.
                first = await self._first_frame(source, workdir / "first")
                if first is None:
                    return []
                candidates = [first]
            hashes = await self._hashes(candidates)
            kept = self._dedupe(candidates, hashes, limit=min(profile.max_frames, self._max_frames))
            frames: list[ExtractedFrame] = []
            for index, candidate in enumerate(kept, start=1):
                data = await asyncio.to_thread(candidate.path.read_bytes)
                if not data:
                    continue
                frames.append(ExtractedFrame(index=index, at_sec=candidate.at_sec, data=data))
            return frames
        finally:
            await asyncio.to_thread(shutil.rmtree, workdir, True)

    # --- ffmpeg -------------------------------------------------------------------------

    async def _safe_candidates(
        self, source: Path, out_dir: Path, profile: FrameProfile, *, mode: str
    ) -> list[FrameCandidate]:
        """Проход кадров без падения всей обработки: пустой список — вызывающий даёт warning."""
        try:
            return await self._candidates(source, out_dir, profile, mode=mode)
        except FrameExtractionError as error:
            logger.warning("Не удалось получить кадры (%s): %s", mode, error)
            return []

    async def _first_frame(self, source: Path, out_dir: Path) -> FrameCandidate | None:
        """Первый кадр записи: страховка для коротких видео и статичного экрана."""
        await asyncio.to_thread(out_dir.mkdir, parents=True, exist_ok=True)
        path = out_dir / "first.jpg"
        try:
            await self._run(
                [
                    self._ffmpeg,
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    *INPUT_GUARD,
                    "-i",
                    str(source),
                    "-an",
                    "-frames:v",
                    "1",
                    "-vf",
                    f"scale={self._width}:-2",
                    "-q:v",
                    str(_FRAME_QUALITY),
                    str(path),
                ]
            )
        except FrameExtractionError:
            return None
        exists = await asyncio.to_thread(path.exists)
        return FrameCandidate(at_sec=0.0, path=path) if exists else None

    async def _candidates(
        self, source: Path, out_dir: Path, profile: FrameProfile, *, mode: str
    ) -> list[FrameCandidate]:
        """Один проход ffmpeg: файлы кадров и их `pts_time` из `showinfo`."""
        await asyncio.to_thread(out_dir.mkdir, parents=True, exist_ok=True)
        pattern = out_dir / "frame_%05d.jpg"
        if mode == "scene":
            selector = f"select='gt(scene,{profile.scene_threshold:g})'"
        else:
            selector = f"fps=1/{profile.min_interval_sec:g}"
        filters = f"{selector},scale={self._width}:-2,showinfo"
        try:
            await self._run(
                [
                    self._ffmpeg,
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "info",
                    "-y",
                    *INPUT_GUARD,
                    "-i",
                    str(source),
                    "-an",
                    "-vf",
                    filters,
                    "-fps_mode",
                    "vfr",
                    "-q:v",
                    str(_FRAME_QUALITY),
                    str(pattern),
                ]
            )
        except FrameExtractionError:
            # Видео без смен сцены — нормальный случай: ffmpeg пишет «Nothing was written» и
            # выходит с ошибкой. Это не сбой материала, кадров просто нет.
            paths = await asyncio.to_thread(lambda: sorted(out_dir.glob("frame_*.jpg")))
            if not paths and "Nothing was written" in self._last_stderr:
                return []
            if not paths:
                raise
        paths = await asyncio.to_thread(lambda: sorted(out_dir.glob("frame_*.jpg")))
        # showinfo пишет PTS в stderr на каждый выбранный кадр — порядок совпадает с файлами.
        times = [float(value) for value in _PTS.findall(self._last_stderr)]
        if not paths:
            return []
        if len(times) < len(paths):
            # Резерв: время по шагу профиля; лучшее, что можно сделать без PTS.
            step = profile.min_interval_sec if mode == "interval" else 0.0
            times = [index * step for index in range(len(paths))]
        return [
            FrameCandidate(at_sec=max(times[index], 0.0), path=path)
            for index, path in enumerate(paths)
        ]

    async def _hashes(self, candidates: list[FrameCandidate]) -> list[int | None]:
        """dhash всех кадров: ffmpeg один раз на каждую папку, затем попиксельное сравнение.

        Сцены и периодические кадры лежат в разных папках, поэтому хешируются последовательности
        по отдельности; результат сопоставляется по порядку кандидатов. Сбой хеширования не
        отменяет кадры: дедупликация просто не сработает.
        """
        hashes: list[int | None] = []
        for directory in _directories(candidates):
            subset = [item for item in candidates if item.path.parent == directory]
            try:
                values = await self._hash_sequence(directory, len(subset))
            except FrameExtractionError as error:
                logger.warning("Не удалось посчитать dhash кадров: %s", error)
                values = []
            hashes.extend(values if len(values) == len(subset) else [None] * len(subset))
        return hashes

    async def _hash_sequence(self, directory: Path, count: int) -> list[int | None]:
        if count <= 0:
            return []
        raw = await self._run(
            [
                self._ffmpeg,
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(directory / "frame_%05d.jpg"),
                "-vf",
                f"scale={_HASH_SIDE}:{_HASH_SIDE},format=gray",
                "-f",
                "rawvideo",
                "pipe:1",
            ],
            capture=True,
        )
        expected = count * _HASH_BYTES
        if len(raw) < expected:
            return [None] * count
        return [
            _dhash(raw[index * _HASH_BYTES : (index + 1) * _HASH_BYTES]) for index in range(count)
        ]

    async def _run(self, args: list[str], *, capture: bool = False) -> bytes:
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as error:
            raise FrameExtractionError(
                "На сервере недоступен ffmpeg: кадры не извлечены"
            ) from error
        self._last_stderr = ""
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self._timeout)
        except TimeoutError:
            process.kill()
            await process.wait()
            raise FrameExtractionError("Извлечение кадров заняло слишком много времени") from None
        except asyncio.CancelledError:
            process.kill()
            await process.wait()
            raise
        self._last_stderr = stderr.decode(errors="replace")
        if process.returncode != 0:
            level = logging.DEBUG if "Nothing was written" in self._last_stderr else logging.WARNING
            logger.log(
                level,
                "ffmpeg (кадры) завершился с кодом %s: %s",
                process.returncode,
                self._last_stderr[-_STDERR_LOG_LIMIT:],
            )
            raise FrameExtractionError("Не удалось извлечь кадры записи")
        return stdout if capture else b""

    # --- дедупликация -------------------------------------------------------------------

    def _dedupe(
        self,
        candidates: list[FrameCandidate],
        hashes: list[int | None],
        *,
        limit: int,
    ) -> list[FrameCandidate]:
        """Оставляет непохожие кадры; при переполнении — равномерно по всей записи."""
        kept: list[FrameCandidate] = []
        kept_hashes: list[int] = []
        for candidate, value in zip(candidates, hashes, strict=True):
            if kept and candidate.at_sec - kept[-1].at_sec < _MIN_FRAME_GAP_SEC:
                continue
            if value is not None and any(
                _hamming(value, existing) <= self._dedup_bits for existing in kept_hashes
            ):
                continue
            kept.append(candidate)
            if value is not None:
                kept_hashes.append(value)
        if len(kept) <= limit:
            return kept
        # Лучше покрыть всю запись реже, чем потерять конец: выборка включает первый и
        # последний кадр, остальные распределены между ними равномерно.
        if limit == 1:
            return [kept[0]]
        last = len(kept) - 1
        return [kept[round(index * last / (limit - 1))] for index in range(limit)]


def _directories(candidates: list[FrameCandidate]) -> list[Path]:
    seen: list[Path] = []
    for item in candidates:
        if item.path.parent not in seen:
            seen.append(item.path.parent)
    return seen


def _dhash(raw: bytes) -> int:
    """dhash 16×16: 240 бит сравнения соседних пикселей каждой строки."""
    value = 0
    bit = 0
    for row in range(_HASH_SIDE):
        start = row * _HASH_SIDE
        for column in range(_HASH_SIDE - 1):
            if raw[start + column] > raw[start + column + 1]:
                value |= 1 << bit
            bit += 1
    return value


def _hamming(left: int, right: int) -> int:
    return (left ^ right).bit_count()
