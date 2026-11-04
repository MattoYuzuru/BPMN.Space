"""Аудио/видео (ffmpeg, сегменты, склейка) и harness длинных документов (параллельность, срок)."""

# ruff: noqa: PT018, ASYNC221, S607
import asyncio
import json
import shutil
import subprocess
import wave
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.container import build_container
from app.domain.analysis import ContextSource, RunContext
from app.domain.bpmn.ir import GraphIR
from app.domain.concurrency import adaptive_deadline, bounded_gather
from app.domain.models import SourceKind
from app.ingest import media as media_module
from app.ingest.media import (
    FfmpegRunner,
    MediaError,
    MediaProbe,
    MediaTranscriber,
    format_timecode,
    is_media,
    stitch,
)
from app.ingest.stt import MockSpeechToText, NoSpeechError, TimedText, Transcript
from app.llm.base import PipelineError
from app.llm.evidence_context import prepare_evidence_context
from app.llm.question_analysis import QuestionAnalyzer
from app.llm.semantic_review import review_semantics
from app.main import create_app
from tests.conftest import API, create_project
from tests.test_graph_ir import graph_case

NOW = datetime(2026, 11, 1, tzinfo=UTC)


# ---------- bounded_gather и срок прогона ----------


async def test_bounded_gather_keeps_input_order_and_limit() -> None:
    running = peak = 0

    def make(index: int, delay: float) -> Callable[[], object]:
        async def run() -> int:
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(delay)
            running -= 1
            return index

        return run

    # Первые задачи самые медленные: порядок завершения обратный порядку входа.
    factories = [make(i, 0.03 - i * 0.004) for i in range(6)]
    assert await bounded_gather(factories, limit=3) == [0, 1, 2, 3, 4, 5]  # type: ignore[arg-type]
    assert peak == 3


async def test_bounded_gather_sequential_when_limit_is_one() -> None:
    order: list[str] = []

    def make(name: str) -> Callable[[], object]:
        async def run() -> str:
            order.append(f"start {name}")
            await asyncio.sleep(0)
            order.append(f"end {name}")
            return name

        return run

    await bounded_gather([make("a"), make("b")], limit=1)  # type: ignore[arg-type]
    assert order == ["start a", "end a", "start b", "end b"]


async def test_bounded_gather_cancels_siblings_and_raises_original_error() -> None:
    cancelled = 0

    async def slow() -> None:
        nonlocal cancelled
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            cancelled += 1
            raise

    async def boom() -> None:
        await asyncio.sleep(0.01)
        raise PipelineError("упало")

    with pytest.raises(PipelineError, match="упало"):
        await bounded_gather([slow, slow, boom], limit=3)
    assert cancelled == 2


def test_adaptive_deadline_floor_growth_and_hard_max() -> None:
    kwargs = {"per_1k_chars_sec": 4.0, "max_sec": 7200.0}
    assert adaptive_deadline(600, total_chars=0, **kwargs) == 600
    assert adaptive_deadline(600, total_chars=100_000, **kwargs) == 1000
    assert adaptive_deadline(600, total_chars=1_500_000, **kwargs) == 6600
    assert adaptive_deadline(600, total_chars=10_000_000, **kwargs) == 7200
    assert adaptive_deadline(0, total_chars=10**6, **kwargs) is None
    # Потолок не может опустить срок ниже базы; 0 — потолка нет.
    assert adaptive_deadline(600, total_chars=10**6, per_1k_chars_sec=4, max_sec=100) == 600
    assert adaptive_deadline(600, total_chars=10**6, per_1k_chars_sec=4, max_sec=0) == 4600


def test_settings_deadline_and_budget_override() -> None:
    settings = Settings(run_deadline_sec=300, run_deadline_per_1k_chars_sec=2)
    assert settings.run_deadline(50_000) == 400
    assert Settings(run_deadline_sec=0).run_deadline(50_000) is None
    assert settings.context_budget_chars() == 120_000


# ---------- harness: параллельность без смены результата ----------


def _context(text: str, *, parallel: int, budget: int = 2_000, chunk: int = 1_000) -> RunContext:
    source = ContextSource(
        id=uuid4(), kind=SourceKind.TEXT, title="Регламент", content=text, created_at=NOW
    )
    return RunContext(
        project_id=uuid4(),
        project_title="Длинный",
        sources=[source],
        evidence_sources=[source],
        questions=[],
        analysis_budget_chars=budget,
        parallel_requests=parallel,
        chunk_chars=chunk,
    )


class _Tracker:
    def __init__(self) -> None:
        self.running = 0
        self.peak = 0

    async def enter(self, delay: float) -> None:
        self.running += 1
        self.peak = max(self.peak, self.running)
        await asyncio.sleep(delay)
        self.running -= 1


async def _extraction(parallel: int) -> tuple[list[str], int]:
    text = "".join(f"Шаг {i}: оператор проверяет заявку {i}. " for i in range(300))
    tracker = _Tracker()

    async def complete(_system: str, prompt: str) -> str:
        data = json.loads(prompt)
        # Ранние порции отвечают дольше: порядок ответов не совпадает с порядком порций.
        await tracker.enter(0.02 if data["offset"] == 0 else 0.002)
        first = data["text"].split(".")[0]
        return json.dumps({"quotes": [first]}, ensure_ascii=False)

    result = await prepare_evidence_context(_context(text, parallel=parallel), complete)
    return result.sources[0].content.split("\n\n"), tracker.peak


async def test_evidence_extraction_parallel_matches_sequential_order() -> None:
    sequential, peak_one = await _extraction(1)
    parallel, peak_four = await _extraction(4)
    assert parallel == sequential
    assert len(sequential) > 3
    assert peak_one == 1
    assert 1 < peak_four <= 4
    assert sequential[0].startswith("Шаг 0")


async def test_evidence_reduce_compacts_quotes_literally_and_warns() -> None:
    text = "".join(f"Шаг {i}: оператор проверяет заявку {i}. " for i in range(120))
    calls = {"extract": 0, "reduce": 0}

    async def complete(system: str, prompt: str) -> str:
        data = json.loads(prompt)
        if "не помещаются" in system:
            calls["reduce"] += 1
            return json.dumps({"quotes": [data["text"].split("\n\n")[0][:12]]}, ensure_ascii=False)
        calls["extract"] += 1
        # Каждая порция возвращает много цитат: сумма превышает бюджет.
        pieces = [p.strip() + "." for p in data["text"].split(".") if len(p.strip()) > 20]
        return json.dumps({"quotes": pieces[2:-1]}, ensure_ascii=False)

    context = _context(text, parallel=2, budget=2_500, chunk=1_000)
    result = await prepare_evidence_context(context, complete)
    assert calls["reduce"] > 0
    assert len("\n\n".join(q for q in result.sources[0].content.split("\n\n"))) <= 2_500
    assert all(q in text for q in result.sources[0].content.split("\n\n"))
    assert any("сжаты повторным извлечением" in w for w in result.warnings)


async def test_evidence_overflow_after_reduce_is_explicit_refusal() -> None:
    text = "слово " * 2_000

    async def complete(_system: str, prompt: str) -> str:
        return json.dumps({"quotes": [json.loads(prompt)["text"][:900]]})

    with pytest.raises(PipelineError, match="не помещаются в контекст"):
        await prepare_evidence_context(_context(text, parallel=2, budget=2_000), complete)


async def test_semantic_review_parallel_is_ordered_and_bounded() -> None:
    text = "".join(f"Пункт {i}. Заявку проверяет оператор. " for i in range(200))
    context = _context(text, parallel=4, budget=4_000, chunk=1_000)
    graph = GraphIR.model_validate(graph_case("xor"))
    element = graph.nodes[0].id
    source_id = str(context.sources[0].id)
    tracker = _Tracker()

    async def complete(_system: str, prompt: str) -> str:
        data = json.loads(prompt)
        part = data["sources"][0]["text"]
        await tracker.enter(0.02 if part.startswith("Пункт 0") else 0.001)
        marker = part[:8]
        return json.dumps(
            {
                "issues": [
                    {
                        "element_id": element,
                        "source_id": source_id,
                        "quote": marker,
                        "message": f"порция {marker}",
                    }
                ]
            },
            ensure_ascii=False,
        )

    errors = await review_semantics(graph, context, complete)
    sequential = await review_semantics(graph, replace(context, parallel_requests=1), complete)
    assert errors == sequential
    assert errors[0].count("Пункт 0") == 1 or "Пункт 0" in errors[0]
    assert 1 < tracker.peak <= 4


async def test_question_analysis_scan_and_verify_run_in_parallel_in_order() -> None:
    sources = [
        ContextSource(
            id=uuid4(),
            kind=SourceKind.TEXT,
            title=f"Док {i}",
            content=f"Оператор {i} принимает заявку {i}. " * 150,
            created_at=NOW,
        )
        for i in range(5)
    ]
    tracker = _Tracker()
    analyze_order: list[str] = []

    async def complete(_system: str, prompt: str) -> str:
        payload = json.loads(prompt)
        if payload["phase"] == "analyze":
            first = payload["sources"][0]
            await tracker.enter(0.03 if first["title"] == "Док 0" else 0.002)
            analyze_order.append(first["title"])
            quote = first["text"][:20]
            return json.dumps(
                {
                    "complete": True,
                    "question_updates": [],
                    "new_questions": [
                        {
                            "kind": "missing_actor",
                            "severity": "major",
                            "text": f"Кто принимает заявку {first['title']}?",
                            "assumption": "Не определён",
                            "source_id": first["id"],
                            "quote": quote,
                        }
                    ],
                },
                ensure_ascii=False,
            )
        await tracker.enter(0.002)
        return json.dumps(
            {
                "complete": True,
                "decisions": [
                    {"id": p["id"], "valid": True, "reason": "Проверено по цитате"}
                    for p in payload["proposals"]
                ],
            }
        )

    def verify_quote(
        candidates: list[ContextSource], source_id: object, quote: object
    ) -> tuple[UUID | None, str | None]:
        for source in candidates:
            if str(source.id) == source_id and isinstance(quote, str) and quote in source.content:
                return source.id, quote
        return None, None

    async def run(parallel: int) -> list[str]:
        analyzer = QuestionAnalyzer(complete, verify_quote, lambda: "test-model")
        context = RunContext(
            project_id=uuid4(),
            project_title="Параллельность",
            sources=sources,
            evidence_sources=sources,
            questions=[],
            analysis_budget_chars=40_000,
            parallel_requests=parallel,
        )
        result = await analyzer.analyze(context)
        return [q.text for q in result.new_questions]

    sequential = await run(1)
    tracker.peak = 0
    parallel = await run(4)
    assert parallel == sequential
    assert len(sequential) == 5
    assert 1 < tracker.peak <= 4


# ---------- склейка и сегменты ----------


def test_timecodes_and_stitch_order() -> None:
    assert format_timecode(0) == "[00:00]"
    assert format_timecode(65.9) == "[01:05]"
    assert format_timecode(4500) == "[75:00]"
    parts = [
        (600.0, Transcript(text="Второй", duration_sec=600)),
        (0.0, Transcript(text="Первый", duration_sec=600)),
        (1200.0, None),
    ]
    assert stitch(parts) == "[00:00] Первый\n[10:00] Второй"


def test_stitch_groups_utterances_into_timed_blocks() -> None:
    utterances = tuple(
        TimedText(start_sec=start, text=f"реплика {start:g}") for start in (0, 10, 31, 40, 70)
    )
    transcript = Transcript(text="x", duration_sec=80, utterances=utterances)
    assert stitch([(600.0, transcript)]) == (
        "[10:00] реплика 0 реплика 10\n[10:31] реплика 31 реплика 40\n[11:10] реплика 70"
    )


def test_media_extensions() -> None:
    assert is_media("встреча.MP4") and is_media("a.mkv") and is_media("a.flac")
    assert not is_media("a.pdf") and not is_media("a.txt")


class _FakeRunner(FfmpegRunner):
    def __init__(self, *, segments: int, probe: MediaProbe) -> None:
        super().__init__(ffmpeg="ffmpeg", ffprobe="ffprobe", timeout_sec=5)
        self.segments = segments
        self._probe = probe
        self.workdir: Path | None = None

    @property
    def available(self) -> bool:
        return True

    async def probe(self, source: Path) -> MediaProbe:
        return self._probe

    async def segment(self, source: Path, out_dir: Path, *, segment_sec: int) -> list[Path]:
        self.workdir = out_dir
        paths = []
        for index in range(self.segments):
            path = out_dir / f"segment_{index:05d}.ogg"
            path.write_bytes(f"audio-{index}".encode())
            paths.append(path)
        return paths


class _FakeStt:
    def __init__(self, fail: set[int] | None = None, silent: set[int] | None = None) -> None:
        self.fail = fail or set()
        self.silent = silent or set()
        self.running = 0
        self.peak = 0
        self.calls: list[str] = []

    async def transcribe(self, data: bytes, *, mime: str | None) -> Transcript:
        index = int(data.decode().split("-")[1])
        self.calls.append(f"{index}:{mime}")
        self.running += 1
        self.peak = max(self.peak, self.running)
        try:
            await asyncio.sleep(0.02 if index == 0 else 0.001)
            if index in self.fail:
                raise RuntimeError("provider")
            if index in self.silent:
                raise NoSpeechError
            return Transcript(text=f"речь {index}", duration_sec=600)
        finally:
            self.running -= 1


def _transcriber(stt: _FakeStt, runner: FfmpegRunner, **kwargs: object) -> MediaTranscriber:
    return MediaTranscriber(stt, runner, segment_sec=600, parallel_segments=2, **kwargs)  # type: ignore[arg-type]


async def test_segments_are_transcribed_in_parallel_stitched_and_cleaned_up(
    tmp_path: Path,
) -> None:
    source = tmp_path / "meeting.mp4"
    source.write_bytes(b"x")
    runner = _FakeRunner(segments=4, probe=MediaProbe(duration_sec=2300, has_audio=True))
    stt = _FakeStt(silent={2})
    transcript = await _transcriber(stt, runner).transcribe(source)
    assert transcript.text == "[00:00] речь 0\n[10:00] речь 1\n[30:00] речь 3"
    assert transcript.duration_sec == 2300
    assert stt.peak == 2
    assert all(call.endswith("audio/ogg") for call in stt.calls)
    assert runner.workdir is not None and not runner.workdir.exists()


async def test_failed_segment_fails_whole_source_after_retry(tmp_path: Path) -> None:
    source = tmp_path / "a.mp3"
    source.write_bytes(b"x")
    runner = _FakeRunner(segments=3, probe=MediaProbe(duration_sec=1500, has_audio=True))
    stt = _FakeStt(fail={1})
    with pytest.raises(MediaError, match=r"\[10:00\]"):
        await _transcriber(stt, runner, attempts=2).transcribe(source)
    assert stt.calls.count("1:audio/ogg") == 2
    assert runner.workdir is not None and not runner.workdir.exists()


async def test_all_silent_is_no_speech(tmp_path: Path) -> None:
    source = tmp_path / "a.mp3"
    source.write_bytes(b"x")
    runner = _FakeRunner(segments=2, probe=MediaProbe(duration_sec=900, has_audio=True))
    with pytest.raises(NoSpeechError):
        await _transcriber(_FakeStt(silent={0, 1}), runner).transcribe(source)


async def test_no_audio_track_and_duration_limit(tmp_path: Path) -> None:
    source = tmp_path / "v.mp4"
    source.write_bytes(b"x")
    silent = _FakeRunner(segments=1, probe=MediaProbe(duration_sec=10, has_audio=False))
    with pytest.raises(MediaError, match="нет звуковой дорожки"):
        await _transcriber(_FakeStt(), silent).transcribe(source)
    long = _FakeRunner(segments=1, probe=MediaProbe(duration_sec=5 * 3600, has_audio=True))
    with pytest.raises(MediaError, match="длиннее 4 ч"):
        await _transcriber(_FakeStt(), long, max_duration_sec=4 * 3600).transcribe(source)


async def test_segment_timeout_scales_with_length(tmp_path: Path) -> None:
    transcriber = _transcriber(
        _FakeStt(),
        _FakeRunner(segments=1, probe=MediaProbe(10, True)),
        timeout_base_sec=60,
        timeout_per_audio_sec=0.3,
    )
    assert transcriber.segment_timeout(600) == 240
    assert transcriber.segment_timeout(60) == 78

    class Hang:
        async def transcribe(self, data: bytes, *, mime: str | None) -> Transcript:
            await asyncio.sleep(5)
            raise AssertionError

    source = tmp_path / "a.mp3"
    source.write_bytes(b"x")
    quick = MediaTranscriber(
        Hang(),  # type: ignore[arg-type]
        _FakeRunner(segments=1, probe=MediaProbe(10, True)),
        timeout_base_sec=0.05,
        timeout_per_audio_sec=0,
        attempts=1,
    )
    with pytest.raises(MediaError, match="Не удалось расшифровать"):
        await quick.transcribe(source)


async def test_without_ffmpeg_only_mock_stt_fallback_works(tmp_path: Path) -> None:
    source = tmp_path / "a.mp4"
    source.write_bytes(b"x" * 100)
    runner = FfmpegRunner(ffmpeg="no-such-ffmpeg", ffprobe="no-such-ffprobe", timeout_sec=1)
    assert not runner.available
    strict = MediaTranscriber(MockSpeechToText(delay_sec=0), runner)
    with pytest.raises(MediaError, match="не установлен ffmpeg"):
        await strict.transcribe(source)
    lenient = MediaTranscriber(MockSpeechToText(delay_sec=0), runner, raw_fallback=True)
    assert (await lenient.transcribe(source)).text


# ---------- ffmpeg-обёртка ----------


class _Process:
    def __init__(self, code: int, out: bytes = b"", err: bytes = b"", hang: bool = False) -> None:
        self.returncode = code
        self._out, self._err, self._hang = out, err, hang
        self.killed = False

    async def communicate(self) -> tuple[bytes, bytes]:
        if self._hang:
            await asyncio.sleep(5)
        return self._out, self._err

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        return self.returncode


async def test_ffmpeg_command_has_no_shell_and_safe_arguments(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: list[tuple[object, ...]] = []

    async def fake_exec(*args: object, **kwargs: object) -> _Process:
        captured.append(args)
        assert kwargs["stdin"] == asyncio.subprocess.DEVNULL
        return _Process(0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    runner = FfmpegRunner(ffmpeg="ffmpeg", ffprobe="ffprobe", timeout_sec=5)
    (tmp_path / "segment_00001.ogg").write_bytes(b"1")
    (tmp_path / "segment_00000.ogg").write_bytes(b"0")
    paths = await runner.segment(Path("/data/in put.mp4"), tmp_path, segment_sec=600)
    assert [p.name for p in paths] == ["segment_00000.ogg", "segment_00001.ogg"]
    args = [str(a) for a in captured[0]]
    assert args[0] == "ffmpeg" and "-nostdin" in args and "-vn" in args
    assert args[args.index("-i") + 1] == "/data/in put.mp4"  # один аргумент, без shell-разбора
    assert args[args.index("-protocol_whitelist") + 1] == "file"
    assert args.index("-format_whitelist") < args.index("-i")  # входные опции — до `-i`
    assert args[args.index("-segment_time") + 1] == "600"
    assert args[args.index("-ac") + 1] == "1" and args[args.index("-ar") + 1] == "16000"


async def test_ffmpeg_failure_and_timeout_are_user_errors_and_kill_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    processes = [_Process(1, err=b"secret internal path"), _Process(0, hang=True)]

    async def fake_exec(*_args: object, **_kwargs: object) -> _Process:
        return processes.pop(0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    runner = FfmpegRunner(ffmpeg="ffmpeg", ffprobe="ffprobe", timeout_sec=0.05)
    with pytest.raises(MediaError, match="файл повреждён") as failure:
        await runner.segment(tmp_path / "a.mp4", tmp_path, segment_sec=600)
    assert "secret" not in str(failure.value)
    hung = processes[0]
    with pytest.raises(MediaError, match="слишком много времени"):
        await runner.segment(tmp_path / "a.mp4", tmp_path, segment_sec=600)
    assert hung.killed


async def test_ffprobe_output_is_parsed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "streams": [{"codec_type": "video"}, {"codec_type": "audio"}],
            "format": {"duration": "12.5"},
        }
    ).encode()

    async def fake_exec(*_args: object, **_kwargs: object) -> _Process:
        return _Process(0, out=payload)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    runner = FfmpegRunner(ffmpeg="ffmpeg", ffprobe="ffprobe", timeout_sec=5)
    assert await runner.probe(tmp_path / "a.mp4") == MediaProbe(duration_sec=12.5, has_audio=True)


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg и ffprobe не установлены",
)
async def test_real_ffmpeg_splits_wav_into_segments(tmp_path: Path) -> None:
    source = tmp_path / "tone.wav"
    with wave.open(str(source), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\x10\x20" * 8000 * 7)  # 7 секунд
    runner = FfmpegRunner(ffmpeg="ffmpeg", ffprobe="ffprobe", timeout_sec=60)
    probe = await runner.probe(source)
    assert probe.has_audio and 6.5 < probe.duration_sec < 7.5
    out = tmp_path / "out"
    out.mkdir()
    segments = await runner.segment(source, out, segment_sec=3)
    assert len(segments) == 3
    assert all(path.stat().st_size > 0 for path in segments)
    video = tmp_path / "silent.mp4"
    subprocess.run(  # noqa: S603 — фиксированная команда теста
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=64x64:d=1",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
    )
    assert not (await runner.probe(video)).has_audio


# ---------- загрузка записи через API ----------


def _media_client(settings: Settings, **overrides: object) -> TestClient:
    settings = settings.model_copy(update=overrides)
    return TestClient(create_app(settings, container=build_container(settings)))


def test_media_upload_runs_in_background_and_streams_to_storage(settings: Settings) -> None:
    media_module.shutil.which  # noqa: B018 — модуль подключён
    with _media_client(settings, ffmpeg_path="no-such-ffmpeg") as client:
        project_id = create_project(client)
        response = client.post(
            f"{API}/projects/{project_id}/sources/file",
            files={"file": ("встреча.mp4", b"\x00" * 4096, "video/mp4")},
        )
        assert response.status_code == 201
        assert response.json()["status"] == "processing"
        source = next(
            s
            for s in client.get(f"{API}/projects/{project_id}").json()["sources"]
            if s["file_name"] == "встреча.mp4"
        )
        assert source["status"] == "ready"
        assert source["content"]
        assert source["duration_sec"] is None or source["duration_sec"] > 0


def test_media_upload_limit_is_separate_from_document_limit(settings: Settings) -> None:
    with _media_client(settings, max_upload_bytes=100, max_media_bytes=5_000) as client:
        project_id = create_project(client)
        url = f"{API}/projects/{project_id}/sources/file"
        big_doc = client.post(url, files={"file": ("a.txt", b"x" * 500, "text/plain")})
        assert big_doc.status_code == 413
        ok_media = client.post(url, files={"file": ("a.mp3", b"x" * 500, "audio/mpeg")})
        assert ok_media.status_code == 201
        big_media = client.post(url, files={"file": ("b.mp3", b"x" * 6_000, "audio/mpeg")})
        assert big_media.status_code == 413
        assert client.get(f"{API}/projects/{project_id}").json()["counts"]["sources"] == 1


def test_unsupported_extension_lists_documents_and_media(client: TestClient) -> None:
    project_id = create_project(client)
    response = client.post(
        f"{API}/projects/{project_id}/sources/file",
        files={"file": ("a.xls", b"x", "application/octet-stream")},
    )
    assert response.status_code == 415
    detail = response.json()["detail"]
    assert ".xlsx" in detail and ".mp4" in detail


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg и ffprobe не установлены",
)
async def test_real_ffmpeg_accepts_containers_but_not_hls_playlist(tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"\x00" * 64)
    playlist = tmp_path / "disguised.mp3"
    playlist.write_text(f"#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\n{secret}\n")
    runner = FfmpegRunner(ffmpeg="ffmpeg", ffprobe="ffprobe", timeout_sec=30)
    with pytest.raises(MediaError):
        await runner.probe(playlist)
    for name in ("a.mp3", "a.m4a", "a.ogg", "a.flac", "a.webm"):
        target = tmp_path / name
        subprocess.run(  # noqa: S603 — фиксированная команда теста
            ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=d=1", str(target)],
            check=True,
        )
        assert (await runner.probe(target)).has_audio, name
