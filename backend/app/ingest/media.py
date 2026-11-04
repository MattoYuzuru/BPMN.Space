"""Аудио и видео как источник (ADR-0012): ffmpeg → сегменты → STT → текст с таймкодами.

Файл лежит на диске (потоковая загрузка), ffmpeg без shell и с таймаутом извлекает звук,
переводит в mono 16 кГц opus и режет на сегменты по ~10 минут; сегменты расшифровываются с
ограниченной параллельностью и склеиваются в текст со строками `[мм:сс] реплика`. Любой
сегмент, который не удалось расшифровать после повтора, делает весь источник `failed`: тихо
пропущенных кусков записи нет. Временные файлы удаляются всегда.
"""

import asyncio
import json
import logging
import shutil
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import UUID

from app.domain.capabilities import CapabilityOutcome, CapabilityUnavailableError
from app.ingest.stt import NoSpeechError, SpeechToText, Transcript

logger = logging.getLogger(__name__)

AUDIO_EXTENSIONS = (".mp3", ".wav", ".ogg", ".opus", ".m4a", ".flac", ".aac", ".webm")
VIDEO_EXTENSIONS = (".mp4", ".mov", ".mkv")
# Входные опции ffmpeg/ffprobe: только локальный файл и контейнеры из допустимых расширений.
# Без них плейлист HLS под видом .mp3 мог бы читать другие файлы или ходить по сети.
INPUT_GUARD = (
    "-protocol_whitelist",
    "file",
    "-format_whitelist",
    "mp3,wav,ogg,flac,aac,matroska,webm,mov,mp4,m4a,3gp,3g2,mj2",
)
MEDIA_EXTENSIONS = (*AUDIO_EXTENSIONS, *VIDEO_EXTENSIONS)

_SEGMENT_MIME = "audio/ogg"
_STDERR_LOG_LIMIT = 2000
_BLOCK_SEC = 30.0
_RAW_FALLBACK_LIMIT = 60 * 1024 * 1024


def is_media(file_name: str) -> bool:
    return file_name.lower().endswith(MEDIA_EXTENSIONS)


class MediaError(Exception):
    """Не удалось обработать запись. Сообщение — для пользователя."""


class MediaRoutingError(MediaError):
    """Запись не расшифрована, потому что кончились рабочие ключи пользователя (RFC-0006).

    Несёт структурный результат маршрутизатора: причина, что уже покрыто записью, что осталось и
    какие есть альтернативы. Текст провайдера в сообщение не входит.
    """

    def __init__(self, message: str, *, outcome: CapabilityOutcome) -> None:
        super().__init__(message)
        self.outcome = outcome


def format_timecode(seconds: float) -> str:
    total = max(int(seconds), 0)
    return f"[{total // 60:02d}:{total % 60:02d}]"


@dataclass(frozen=True, slots=True)
class MediaProbe:
    duration_sec: float
    has_audio: bool
    has_video: bool = False


@dataclass(slots=True)
class MediaJob:
    """Что обработка записи узнала по пути: дорожки, провайдер и отказ маршрутизации."""

    probe: MediaProbe | None = None
    # Кто и чем расшифровал — для `derivation` производного источника (RFC-0006).
    provider: str | None = None
    model: str | None = None
    cost_usd: float | None = None
    credential_id: UUID | None = None  # чей ключ оплатил расшифровку
    # Структурный результат отказа маршрутизации: причина, покрытый и оставшийся диапазон.
    routing: CapabilityOutcome | None = None


class FfmpegRunner:
    """Тонкая обёртка над ffmpeg/ffprobe: аргументы списком, таймаут, без shell."""

    def __init__(self, *, ffmpeg: str, ffprobe: str, timeout_sec: float) -> None:
        self._ffmpeg = ffmpeg
        self._ffprobe = ffprobe
        self._timeout = timeout_sec

    @property
    def available(self) -> bool:
        return shutil.which(self._ffmpeg) is not None and shutil.which(self._ffprobe) is not None

    async def _run(self, args: list[str], *, timeout_sec: float) -> bytes:
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as error:
            raise MediaError("На сервере недоступен ffmpeg для обработки записи") from error
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_sec)
        except TimeoutError:
            process.kill()
            await process.wait()
            raise MediaError("Обработка записи заняла слишком много времени") from None
        except asyncio.CancelledError:
            process.kill()
            await process.wait()
            raise
        if process.returncode != 0:
            logger.warning(
                "ffmpeg завершился с кодом %s: %s",
                process.returncode,
                stderr.decode(errors="replace")[-_STDERR_LOG_LIMIT:],
            )
            raise MediaError("Не удалось прочитать запись: файл повреждён или формат не поддержан")
        return stdout

    async def probe(self, source: Path) -> MediaProbe:
        out = await self._run(
            [
                self._ffprobe,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_entries",
                "format=duration:stream=codec_type:stream_disposition=attached_pic",
                *INPUT_GUARD,
                str(source),
            ],
            timeout_sec=min(self._timeout, 120.0),
        )
        try:
            data = json.loads(out)
            streams = data.get("streams", [])
            duration = float(data.get("format", {}).get("duration") or 0.0)
        except (ValueError, TypeError, AttributeError):
            raise MediaError("Не удалось определить длительность записи") from None
        has_audio = any(item.get("codec_type") == "audio" for item in streams)
        # Обложка mp3/m4a — тоже видеопоток, но с attached_pic: это не видео.
        has_video = any(
            item.get("codec_type") == "video"
            and not (item.get("disposition") or {}).get("attached_pic")
            for item in streams
        )
        return MediaProbe(duration_sec=duration, has_audio=has_audio, has_video=has_video)

    async def segment(self, source: Path, out_dir: Path, *, segment_sec: int) -> list[Path]:
        """Звук → mono 16 кГц opus сегментами по `segment_sec`; пути по порядку записи."""
        pattern = out_dir / "segment_%05d.ogg"
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
                "-vn",
                "-map",
                "0:a:0",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "libopus",
                "-b:a",
                "24k",
                "-f",
                "segment",
                "-segment_time",
                str(segment_sec),
                "-reset_timestamps",
                "1",
                str(pattern),
            ],
            timeout_sec=self._timeout,
        )
        return await asyncio.to_thread(lambda: sorted(out_dir.glob("segment_*.ogg")))


def stitch(parts: list[tuple[float, Transcript | None]], *, block_sec: float = _BLOCK_SEC) -> str:
    """Склеивает сегменты по времени: `[мм:сс] текст`; реплики с таймкодами объединяются в блоки.

    `parts` — пары «смещение сегмента, расшифровка» (None — тишина). Порядок строго по смещению.
    """
    lines: list[str] = []
    for offset, transcript in sorted(parts, key=lambda item: item[0]):
        if transcript is None:
            continue
        if not transcript.utterances:
            lines.append(f"{format_timecode(offset)} {transcript.text.strip()}")
            continue
        block_start = 0.0
        block: list[str] = []
        for item in transcript.utterances:
            if block and item.start_sec - block_start >= block_sec:
                lines.append(f"{format_timecode(offset + block_start)} {' '.join(block)}")
                block = []
            if not block:
                block_start = item.start_sec
            block.append(item.text)
        if block:
            lines.append(f"{format_timecode(offset + block_start)} {' '.join(block)}")
    return "\n".join(lines)


class MediaTranscriber:
    def __init__(
        self,
        stt: SpeechToText,
        runner: FfmpegRunner,
        *,
        segment_sec: int = 600,
        parallel_segments: int = 3,
        max_duration_sec: float = 4 * 3600.0,
        timeout_base_sec: float = 60.0,
        timeout_per_audio_sec: float = 0.3,
        max_concurrent_jobs: int = 1,
        raw_fallback: bool = False,
        attempts: int = 2,
        provider: str = "mock",
        model: str | None = None,
        routing_deadline_sec: float = 0.0,
    ) -> None:
        self.provider = provider  # для `derivation` производной расшифровки (RFC-0006)
        self.model = model
        self._stt = stt
        self._runner = runner
        self._segment_sec = segment_sec
        self._parallel = parallel_segments
        self._max_duration = max_duration_sec
        self._timeout_base = timeout_base_sec
        self._timeout_per_audio = timeout_per_audio_sec
        self._jobs = max_concurrent_jobs
        self._raw_fallback = raw_fallback
        self._attempts = attempts
        # Запас времени на перебор ключей и запасной серверный путь внутри маршрутизатора:
        # сам маршрутизатор ограничивает один вызов адаптера, а этот дедлайн не даёт
        # оборвать его до перехода к следующему ключу.
        self._routing_deadline = max(routing_deadline_sec, 0.0)
        self._semaphore: asyncio.Semaphore | None = None

    def segment_timeout(self, duration_sec: float) -> float:
        return self._timeout_base + self._timeout_per_audio * max(duration_sec, 0.0)

    def params(self) -> dict[str, object]:
        """Параметры сегментации для `derivation.params` производной расшифровки."""
        return {
            "segment_sec": self._segment_sec,
            "block_sec": _BLOCK_SEC,
            "audio": "opus mono 16 kHz",
            "ffmpeg": self._runner.available,
        }

    async def transcribe(
        self,
        source: Path,
        *,
        job: MediaJob | None = None,
        stt: SpeechToText | None = None,
    ) -> Transcript:
        """Расшифровка файла записи; `MediaError` / `NoSpeechError` при неудаче.

        `stt` — адаптер возможного ключа пользователя-инициатора записи (RFC-0006); без него
        работает серверный провайдер (`STT_PROVIDER`/`DEEPGRAM_API_KEY`) — прежнее поведение.
        ffprobe, ffmpeg и STT идут одной задачей под общим семафором (`max_concurrent_jobs`).
        `job.probe` получает дорожки записи, как только ffprobe их прочитал, — и при сбое
        расшифровки тоже; `job.routing` — структурный результат отказа маршрутизации.
        """
        engine = stt or self._stt
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._jobs)
        async with self._semaphore:
            if not self._runner.available:
                return await self._without_ffmpeg(source, engine, job)
            probe = await self._runner.probe(source)
            if job is not None:
                job.probe = probe
            return await self._with_ffmpeg(source, probe, engine, job)

    async def _without_ffmpeg(
        self, source: Path, engine: SpeechToText, job: MediaJob | None
    ) -> Transcript:
        """Без ffmpeg работает только mock-STT на небольшом файле, чтобы демо не ломалось."""
        if not self._raw_fallback:
            raise MediaError("На сервере не установлен ffmpeg: записи пока не обрабатываются")
        size = (await asyncio.to_thread(source.stat)).st_size
        if size > _RAW_FALLBACK_LIMIT:
            raise MediaError("Файл слишком большой для обработки без ffmpeg")
        data = await asyncio.to_thread(source.read_bytes)
        transcript = await engine.transcribe(data, mime=None)
        if job is not None:
            job.provider = transcript.provider or self.provider
            job.model = transcript.model or self.model
            job.cost_usd = transcript.cost_usd
            job.credential_id = transcript.credential_id
        return transcript

    async def _with_ffmpeg(
        self,
        source: Path,
        probe: MediaProbe,
        engine: SpeechToText,
        job: MediaJob | None,
    ) -> Transcript:
        if not probe.has_audio:
            raise MediaError("В файле нет звуковой дорожки")
        if probe.duration_sec > self._max_duration:
            hours = self._max_duration / 3600
            raise MediaError(f"Запись длиннее {hours:g} ч. Разделите её на части")
        workdir = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="media-"))
        segments: list[Path] = []
        try:
            segments = await self._runner.segment(source, workdir, segment_sec=self._segment_sec)
            if not segments:
                raise MediaError("В записи не найдено звука для расшифровки")
            results = await self._collect_segments(
                [
                    self._segment_factory(index, path, probe.duration_sec, engine)
                    for index, path in enumerate(segments)
                ]
            )
        finally:
            await asyncio.to_thread(shutil.rmtree, workdir, True)
        failed_index, failure = _first_failure(results)
        if failure is not None:
            if isinstance(failure, CapabilityUnavailableError):
                # Покрытие — непрерывный префикс успешных сегментов: индекс, а не тайминг.
                outcome = replace(
                    failure.outcome,
                    **self._covered_range(failed_index or 0, probe.duration_sec),
                )
                if job is not None:
                    job.routing = outcome
                raise MediaRoutingError(self._routing_message(outcome), outcome=outcome) from None
            raise failure
        parts = [item for item in results if not isinstance(item, BaseException)]
        text = stitch(parts)
        if not text.strip():
            raise NoSpeechError
        transcripts = [item for _, item in parts if item is not None]
        provider = next((item.provider for item in transcripts if item.provider), None)
        model = next((item.model for item in transcripts if item.model), None)
        costs = [item.cost_usd for item in transcripts if item.cost_usd is not None]
        cost_usd = sum(costs) if costs else None
        credential_id = next(
            (item.credential_id for item in transcripts if item.credential_id is not None), None
        )
        if job is not None:
            job.provider = provider or self.provider
            job.model = model or self.model
            job.cost_usd = cost_usd
            job.credential_id = credential_id
        return Transcript(
            text=text,
            duration_sec=probe.duration_sec,
            provider=provider or self.provider,
            model=model or self.model,
            cost_usd=cost_usd,
            credential_id=credential_id,
        )

    async def _collect_segments(
        self,
        factories: list[Callable[[], Awaitable[tuple[float, Transcript | None]]]],
    ) -> list[tuple[float, Transcript | None] | BaseException]:
        """Ждёт все сегменты, не отменяя остальные при ошибке одного.

        Отмена нарушила бы покрытие: успешный сегмент мог не успеть отметиться, и `done`
        зависел бы от гонки. Ошибка возвращается значением и обрабатывается после того, как
        все запущенные сегменты завершились; параллельность ограничена семафором.
        """
        semaphore = asyncio.Semaphore(self._parallel)

        async def run(
            factory: Callable[[], Awaitable[tuple[float, Transcript | None]]],
        ) -> tuple[float, Transcript | None] | BaseException:
            async with semaphore:
                try:
                    return await factory()
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    return error

        return list(await asyncio.gather(*(run(factory) for factory in factories)))

    def _covered_range(self, failed_index: int, duration_sec: float) -> dict[str, str | None]:
        """Непрерывно покрытый отрезок записи до первого отказавшего сегмента.

        Сегменты одинаковой длины, поэтому покрытие считается по индексу: `failed_index`
        успешных сегментов идут подряд с начала записи. Так `done`/`remaining` не зависят от
        того, в каком порядке завершились параллельные сегменты.
        """
        covered = min(float(failed_index) * self._segment_sec, duration_sec)
        done = f"00:00–{self._clock(covered)}" if covered > 0 else None
        remaining = (
            f"{self._clock(covered)}–{self._clock(duration_sec)}"
            if covered < duration_sec
            else None
        )
        return {"done": done, "remaining": remaining}

    @staticmethod
    def _clock(seconds: float) -> str:
        total = max(int(seconds), 0)
        return f"{total // 60:02d}:{total % 60:02d}"

    def _routing_message(self, outcome: CapabilityOutcome) -> str:
        """Понятный текст для источника: причина и что именно не расшифровано."""
        parts = [outcome.message or "Запись не расшифрована: нет рабочего ключа распознавания"]
        if outcome.done:
            parts.append(f"обработано {outcome.done}")
        if outcome.remaining:
            parts.append(f"не расшифровано {outcome.remaining}")
        return ". ".join(parts)

    def _segment_factory(
        self,
        index: int,
        path: Path,
        total_sec: float,
        engine: SpeechToText,
    ) -> Callable[[], Awaitable[tuple[float, Transcript | None]]]:
        offset = float(index * self._segment_sec)
        duration = max(min(float(self._segment_sec), total_sec - offset), 1.0)

        async def run() -> tuple[float, Transcript | None]:
            data = await asyncio.to_thread(path.read_bytes)
            for attempt in range(1, self._attempts + 1):
                try:
                    transcript = await asyncio.wait_for(
                        engine.transcribe(data, mime=_SEGMENT_MIME),
                        timeout=self.segment_timeout(duration) + self._routing_deadline,
                    )
                except NoSpeechError:
                    return offset, None
                except CapabilityUnavailableError:
                    # Маршрутизатор уже повторил временные сбои и перебрал ключи: не умножаем.
                    raise
                except (RuntimeError, TimeoutError):
                    if attempt == self._attempts:
                        raise MediaError(
                            f"Не удалось расшифровать фрагмент записи с {format_timecode(offset)}. "
                            "Повторите загрузку позже"
                        ) from None
                else:
                    return offset, transcript
            raise AssertionError  # pragma: no cover

        return run


# Приоритет причины, когда отказали несколько сегментов: показываем корень, а не следствие.
# Например, при исчерпанной квоте соседние сегменты падают с «нет рабочего ключа», но
# пользователю и техническому вопросу нужна причина «квота».
_REASON_PRIORITY = {
    "quota_exhausted": 5,
    "auth": 4,
    "unsupported": 3,
    "transient": 2,
    "fatal": 1,
}


def _routing_priority(error: BaseException) -> int:
    if isinstance(error, CapabilityUnavailableError):
        return _REASON_PRIORITY.get(error.outcome.reason or "", 0)
    return 0


def _first_failure(
    results: list[tuple[float, Transcript | None] | BaseException],
) -> tuple[int | None, BaseException | None]:
    """Покрытие — по первому отказавшему сегменту, причина — по самому содержательному.

    Непосредственная ошибка сегмента (например, повреждённый фрагмент) важнее отказа
    маршрутизации: она и становится причиной. Среди отказов маршрутизации выбирается
    корневая причина по классу (квота важнее «нет рабочего ключа» у соседних сегментов).
    """
    failures = [
        (index, item) for index, item in enumerate(results) if isinstance(item, BaseException)
    ]
    if not failures:
        return None, None
    for index, item in failures:
        if not isinstance(item, CapabilityUnavailableError):
            return index, item
    coverage_index = failures[0][0]
    primary = max(failures, key=lambda pair: _routing_priority(pair[1]))[1]
    return coverage_index, primary
