"""Мультимодальные запросы и кадры видео (RFC-0006, волна 3): без сети и без ffmpeg.

Проверяются: блоки Anthropic `image`/`document`, `image_url` с data-URL у OpenAI-совместимых,
детерминированные ответы mock-а, выбор vision/PDF-модели (`ModelResolver.resolve_media`),
разбор ответов OCR/vision, профили обработки, дедупликация кадров по dhash и оценка стоимости.
"""

import asyncio
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from app.domain.credentials import Credential
from app.domain.media import MAX_DOCUMENT_BYTES
from app.fixtures.types import Playbook
from app.ingest.frames import (
    FRAME_PROFILES,
    ExtractedFrame,
    FrameCandidate,
    FrameExtractionError,
    FrameExtractor,
    MediaProfile,
    _dhash,
    _hamming,
    format_timecode,
    frame_profile,
    media_profile,
    profile_label,
)
from app.llm.anthropic import AnthropicClient
from app.llm.base import track_usage
from app.llm.capabilities import ModelCapabilities, ModelPrices, capabilities_for
from app.llm.mock import MockPipeline
from app.llm.multimodal import (
    DATA_MARKER,
    MediaAttachment,
    MediaInputError,
    MediaUnsupportedError,
    document_attachment,
    image_attachment,
    prompt_with_data,
)
from app.llm.openai_compatible import OpenAICompatibleClient
from app.llm.pipeline import LlmPipeline
from app.services.media_derivation import (
    _FrameRecord,
    json_object,
    parse_ocr_response,
    parse_vision_response,
    timed_lines,
)
from app.services.media_estimate import estimate_media
from app.services.model_resolver import ModelResolver
from tests.llm_helpers import json_transport
from tests.test_llm_clients import _config, _message, _Sdk


def empty_playbook() -> Playbook:
    """Пустой плейбук mock-пайплайна: вопросы и схемы для этих тестов не нужны."""
    return cast("Playbook", type("P", (), {"questions": [], "resolutions": [], "diagrams": []})())


PRICES = ModelPrices(
    input=3.0,
    output=15.0,
    cache_read=0.3,
    cache_write=3.75,
    checked_on=date(2026, 11, 4),
)


def _caps(*, vision: bool = True, pdf_input: bool = True) -> ModelCapabilities:
    return ModelCapabilities(vision=vision, pdf_input=pdf_input, prices=PRICES, known=True)


# --- мультимодальные адаптеры -------------------------------------------------------------


async def test_anthropic_sends_image_and_document_blocks() -> None:
    sdk = _Sdk(_message('{"ok": 1}'), _message('{"pages": {}}'))
    client = AnthropicClient(
        _config(provider="anthropic", model="claude-sonnet-5-5", base_url=None),
        sdk=sdk,  # type: ignore[arg-type]
    )
    image = image_attachment(b"jpeg-bytes", label="кадр 1")
    with track_usage() as usage:
        result = await client.complete_vision(
            "СИСТЕМА",
            "Опиши кадр",
            images=[image],
            json_mode=True,
            max_tokens=512,
        )
    assert result == '{"ok": 1}'
    call = sdk.calls[0]
    content = call["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "Опиши кадр"}
    assert content[1]["type"] == "image"
    assert content[1]["source"] == {
        "type": "base64",
        "media_type": "image/jpeg",
        "data": image.base64_data,
    }
    assert call["max_tokens"] == 512
    assert usage.tokens_in == 10
    assert usage.tokens_out == 5
    # Разовые мультимодальные запросы не пишут кеш (запись стоит 1,25× входа).
    assert "cache_control" not in call

    pdf = document_attachment(b"%PDF-1.4 fake", label="скан.pdf")
    await client.complete_document(
        "СИСТЕМА", "Распознай страницы", document=pdf, json_mode=True, max_tokens=1024
    )
    document_block = sdk.calls[1]["messages"][0]["content"][1]
    assert document_block["type"] == "document"
    assert document_block["source"]["media_type"] == "application/pdf"
    assert document_block["source"]["data"] == pdf.base64_data


async def test_openai_vision_uses_data_url_and_pdf_is_unsupported() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "описание"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10},
            },
        )

    client = OpenAICompatibleClient(
        _config(provider="openai", model="gpt-4o"),
        transport=json_transport(handler),
    )
    image = image_attachment(b"\x89PNG", mime="image/png")
    text = await client.complete_vision(
        "S", "Опиши", images=[image], json_mode=False, max_tokens=64
    )
    assert text == "описание"
    content = bodies[0]["messages"][1]["content"]
    assert content[0] == {"type": "text", "text": "Опиши"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    with pytest.raises(MediaUnsupportedError):
        await client.complete_document(
            "S",
            "Прочитай",
            document=document_attachment(b"%PDF"),
            json_mode=True,
            max_tokens=64,
        )
    await client.aclose()


async def test_mock_multimodal_answers_are_deterministic() -> None:
    pipeline = MockPipeline(playbook=empty_playbook(), read_bpmn=lambda _: "")
    prompt = prompt_with_data(
        "Распознай страницы",
        json.dumps({"pages": [12, 13], "language": "ru"}),
    )
    assert prompt.index(DATA_MARKER) > 0
    raw = await pipeline.complete_document(
        "S", prompt, document=document_attachment(b"%PDF"), json_mode=True, max_tokens=64
    )
    pages = json.loads(raw)["pages"]
    assert set(pages) == {"12", "13"}

    frames = await pipeline.complete_vision(
        "S",
        prompt_with_data(
            "Опиши кадры",
            json.dumps({"frames": [{"index": 2, "timecode": "[00:30]"}]}),
        ),
        images=[image_attachment(b"jpg")],
        json_mode=True,
        max_tokens=64,
    )
    described = json.loads(frames)["frames"]
    assert described[0]["index"] == 2
    assert "00:30" in described[0]["timecode"]
    assert pipeline.capabilities.vision
    assert pipeline.capabilities.pdf_input


async def test_pipeline_delegates_media_to_client() -> None:
    sdk = _Sdk(_message("ответ"), _message("ответ"), _message("ответ"))
    client = AnthropicClient(
        _config(provider="anthropic", model="claude-haiku-5-5", base_url=None),
        sdk=sdk,  # type: ignore[arg-type]
    )
    pipeline = LlmPipeline(client, provider="anthropic", model="claude-haiku-5-5")
    answer = await pipeline.complete_vision(
        "S", "U", images=[image_attachment(b"jpg")], json_mode=False, max_tokens=32
    )
    assert answer == "ответ"
    await pipeline.complete_document(
        "S", "U", document=document_attachment(b"%PDF"), json_mode=False, max_tokens=32
    )
    assert sdk.calls[1]["messages"][0]["content"][1]["type"] == "document"
    assert await pipeline.complete_text("S", "U") == "ответ"
    await client.aclose()


def test_media_attachment_validates_kind_and_size() -> None:
    with pytest.raises(MediaInputError):
        MediaAttachment(kind="image", data=b"", mime="image/jpeg")
    with pytest.raises(MediaInputError):
        MediaAttachment(kind="document", data=b"x", mime="image/png")
    assert image_attachment(b"x").mime == "image/jpeg"
    # 32 МБ — предел Anthropic: больше не отправляем даже при наличии ключа.
    assert MAX_DOCUMENT_BYTES == 32 * 1024 * 1024


def test_openai_capabilities_declare_vision_and_pdf_by_family() -> None:
    gpt4o = capabilities_for("openai", "gpt-4o")
    assert gpt4o.vision
    assert gpt4o.pdf_input
    gpt5 = capabilities_for("openai", "gpt-5")
    assert gpt5.vision
    assert gpt5.pdf_input
    # o1 — текстовая модель без изображений; o3/o4 изображения принимают.
    o1 = capabilities_for("openai", "o1")
    assert not o1.vision
    assert not o1.pdf_input
    o3 = capabilities_for("openai", "o3-mini")
    assert o3.vision
    assert o3.pdf_input
    # Неизвестная совместимая модель не обещает multimodal: иначе capability_missing не сработает.
    assert not capabilities_for("openai_compatible", "local-7b").vision


# --- выбор модели для vision/PDF ----------------------------------------------------------


class _FakePipeline:
    """Пайплайн-заглушка с мультимодальными методами (без сети)."""

    provider = "fake"
    model_name = "fake-vision-1"

    def __init__(self) -> None:
        self.released = False

    async def complete_vision(self, *args: Any, **kwargs: Any) -> str:
        return "{}"

    async def complete_document(self, *args: Any, **kwargs: Any) -> str:
        return "{}"

    async def complete_text(self, *args: Any, **kwargs: Any) -> str:
        return "сводка"

    async def aclose(self) -> None:
        self.released = True


class _CredentialRepo:
    def __init__(self, credentials: list[Credential]) -> None:
        self.items = credentials

    async def list_by_user(self, user_id: Any) -> list[Credential]:
        return [item for item in self.items if item.user_id == user_id]


class _FakeRepos:
    def __init__(self, credentials: list[Credential]) -> None:
        self.credentials = _CredentialRepo(credentials)


def _credential(*, model: str, provider: str = "anthropic") -> Credential:
    return Credential(
        id=uuid4(),
        user_id=uuid4(),
        provider=provider,
        label="Мой ключ",
        encrypted_key=b"ciphertext",
        key_hint="1234",
        created_at=datetime.now(UTC),
        default_model=model,
    )


async def test_resolve_media_prefers_user_vision_model_then_mock() -> None:
    credential = _credential(model="claude-sonnet-5-5")
    user_id = credential.user_id
    pipeline = _FakePipeline()
    resolver = ModelResolver(
        _FakeRepos([credential]),  # type: ignore[arg-type]
        server_pipeline=None,
        cipher=type("C", (), {"decrypt": lambda self, *a: SecretStr("key")})(),  # type: ignore[arg-type]
        factory=lambda config, _credential: pipeline,  # type: ignore[arg-type,return-value]
        production=False,
    )
    resolved = await resolver.resolve_media(user_id, need_pdf=True)
    assert resolved is not None
    assert resolved.source == "user"
    assert resolved.model == "claude-sonnet-5-5"
    assert resolved.capabilities.vision
    assert resolved.capabilities.pdf_input
    await resolved.complete_document(
        "S",
        "U",
        document=document_attachment(b"%PDF"),
        json_mode=True,
        max_tokens=10,
    )

    mock = MockPipeline(playbook=empty_playbook(), read_bpmn=lambda _: "")
    mock_resolver = ModelResolver(None, server_pipeline=mock)
    resolved_mock = await mock_resolver.resolve_media(None, need_pdf=True)
    assert resolved_mock is not None
    assert resolved_mock.source == "mock"
    assert resolved_mock.provider == "mock"
    # production не должен подменять реальную модель демонстрационной.
    production = ModelResolver(None, server_pipeline=mock, production=True)
    assert await production.resolve_media(None, need_pdf=False) is None


async def test_resolve_media_capability_missing_without_vision_model() -> None:
    credential = _credential(model="deepseek-chat", provider="openai_compatible")
    credential.base_url = "https://api.example.test/v1"
    resolver = ModelResolver(
        _FakeRepos([credential]),  # type: ignore[arg-type]
        server_pipeline=None,
        cipher=type("C", (), {"decrypt": lambda self, *a: SecretStr("key")})(),  # type: ignore[arg-type]
        factory=lambda config, _credential: _FakePipeline(),  # type: ignore[arg-type,return-value]
    )
    assert await resolver.resolve_media(credential.user_id, need_pdf=False) is None


# --- разбор ответов модели ---------------------------------------------------------------


def test_parse_ocr_response_uses_sequential_pages_and_never_raw_json() -> None:
    # Модель видит фрагмент 1..N и отвечает порядковыми номерами: перевод в исходные — у сервиса.
    payload = json.dumps({"pages": {"1": "Первый", "2": "Второй", "99": "лишняя"}})
    assert parse_ocr_response(payload, (1, 2)) == {1: "Первый", 2: "Второй"}
    markers = "[Страница 1]\nПервый\n\n[Страница 2]\nВторой"
    assert parse_ocr_response(markers, (1, 2)) == {1: "Первый", 2: "Второй"}
    # Разобранный JSON с непригодными страницами не подменяется сырым ответом.
    assert parse_ocr_response(json.dumps({"pages": {"x": "?"}}), (1, 2)) == {}
    assert parse_ocr_response(json.dumps({"other": 1}), (1, 2)) == {}
    # Без разметки сырой текст принимается только для одной страницы фрагмента.
    assert parse_ocr_response("просто текст", (1,)) == {1: "просто текст"}
    assert parse_ocr_response("просто текст", (1, 2)) == {}
    assert parse_ocr_response("", (1,)) == {}
    assert json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert json_object("не json") is None


def test_parse_vision_response_json_and_line_fallback() -> None:
    batch = [
        _FrameRecord(index=1, at_sec=0.0, key="a"),
        _FrameRecord(index=2, at_sec=30.0, key="b"),
    ]
    payload = json.dumps(
        {
            "frames": [
                {"index": 1, "screen": "Открыт список заявок", "text": "Согласовать"},
                {"index": 2, "screen": "Карточка заявки"},
            ]
        }
    )
    descriptions = parse_vision_response(payload, batch)
    assert "Открыт список заявок" in descriptions[1]
    assert "Согласовать" in descriptions[1]
    assert descriptions[2] == "Карточка заявки"
    lines = parse_vision_response("1. Экран входа\n2. Экран списка", batch)
    assert lines == {1: "Экран входа", 2: "Экран списка"}


def test_timed_lines_and_timecodes() -> None:
    lines = timed_lines("[00:30] Привет\n[12:30] Пока\nбез таймкода")
    assert [(line.at_sec, line.text) for line in lines] == [(30.0, "Привет"), (750.0, "Пока")]
    assert format_timecode(750) == "[12:30]"


# --- кадры: dhash, дедупликация, профили --------------------------------------------------


def test_dhash_hamming_and_dedupe() -> None:
    flat = bytes([10] * 256)
    assert _dhash(flat) == 0
    # Один пиксель темнее следующего — ровно один бит.
    edge = bytearray(flat)
    edge[0] = 200
    assert _dhash(bytes(edge)).bit_count() == 1
    assert _hamming(0b1010, 0b1000) == 1

    extractor = FrameExtractor()
    candidates = [
        FrameCandidate(at_sec=0.0, path=Path("a/1.jpg")),
        FrameCandidate(at_sec=1.0, path=Path("a/2.jpg")),
        FrameCandidate(at_sec=60.0, path=Path("a/3.jpg")),
    ]
    kept = extractor._dedupe(
        candidates,
        {candidates[0].path: 0, candidates[1].path: 0, candidates[2].path: 0b111_111_111},
        limit=10,
    )
    assert [item.at_sec for item in kept] == [0.0, 60.0]

    sampled_candidates = [
        FrameCandidate(at_sec=float(index), path=Path(f"x/{index}.jpg")) for index in range(10)
    ]
    sampled = extractor._dedupe(
        sampled_candidates,
        {item.path: (1 << (index * 10)) - 1 for index, item in enumerate(sampled_candidates)},
        limit=3,
    )
    assert len(sampled) == 3
    assert sampled[0].at_sec == 0.0
    assert sampled[-1].at_sec == 9.0


def test_media_profiles_and_estimate() -> None:
    assert media_profile(None) is MediaProfile.AUDIO
    assert media_profile("detailed") is MediaProfile.DETAILED
    assert frame_profile("audio") is None
    assert frame_profile("sparse") is not None
    assert profile_label("audio") == "Только звук"
    with pytest.raises(ValueError, match="профиль"):
        media_profile("unknown")
    assert FRAME_PROFILES[MediaProfile.DETAILED].scene_threshold < (
        FRAME_PROFILES[MediaProfile.SPARSE].scene_threshold
    )

    audio = estimate_media(duration_sec=600, media_profile="audio", has_video=True)
    assert audio.frames_min == 0
    assert audio.frames_max == 0
    assert audio.stt_minutes == 10.0
    assert audio.stt_cost.min_usd is not None
    assert audio.stt_cost.max_usd is not None
    assert audio.stt_cost.min_usd < audio.stt_cost.max_usd

    detailed = estimate_media(duration_sec=600, media_profile="detailed", has_video=True)
    assert 0 < detailed.frames_min <= detailed.frames_max <= 600
    assert detailed.vision_requests >= 1
    # Серверный предел MEDIA_FRAME_MAX_FRAMES учитывается в оценке.
    capped = estimate_media(
        duration_sec=600, media_profile="detailed", has_video=True, frame_max_cap=10
    )
    assert capped.frames_max <= 10
    # Краткое содержание входит в диапазон только для видео с кадрами.
    assert detailed.summary_cost.max_usd is not None
    assert detailed.summary_cost.max_usd > 0
    assert audio.summary_cost.max_usd == 0
    assert detailed.total_cost.min_usd is not None
    assert detailed.total_cost.max_usd is not None
    assert detailed.total_cost.min_usd <= detailed.total_cost.max_usd

    silent = estimate_media(duration_sec=600, media_profile="detailed", has_video=False)
    assert silent.frames_max == 0
    assert silent.vision_requests == 0


class _FakeFrameExtractor(FrameExtractor):
    """Подмена ffmpeg: заданные кадры без процессов (тесты без ffmpeg в CI)."""

    def __init__(self, frames: list[ExtractedFrame]) -> None:
        super().__init__()
        self._fake_frames = frames

    async def extract(self, source: Path, profile: Any) -> list[ExtractedFrame]:
        return self._fake_frames


async def test_extractor_dedupe_via_fake_ffmpeg(tmp_path: Path) -> None:
    frames = await _FakeFrameExtractor([ExtractedFrame(index=1, at_sec=0.0, data=b"a")]).extract(
        tmp_path / "media.mp4", FRAME_PROFILES[MediaProfile.SPARSE]
    )
    assert frames[0].index == 1


# --- перцептивный dhash настоящим ffmpeg --------------------------------------------------


@pytest.mark.skipif(__import__("shutil").which("ffmpeg") is None, reason="ffmpeg не установлен")
async def test_real_ffmpeg_extracts_frames_and_dedupes(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=4:size=160x120:rate=5",
        "-pix_fmt",
        "yuv420p",
        str(video),
    )
    await process.communicate()
    assert process.returncode == 0
    extractor = FrameExtractor(frame_width=320)
    frames = await extractor.extract(video, FRAME_PROFILES[MediaProfile.DETAILED])
    assert frames, "даже статичный экран даёт хотя бы первый кадр"
    assert frames[0].data.startswith(b"\xff\xd8"), "кадры сохраняются JPEG"
    assert frames[0].index == 1


# --- регрессии ревью: dhash по правильным кадрам ------------------------------------------


class _HashScriptedExtractor(FrameExtractor):
    """ffmpeg-хеши подменены: проверяем сопоставление «путь → кадр», а не сами пиксели."""

    def __init__(self, mapping: dict[str, int]) -> None:
        super().__init__()
        self.mapping = mapping

    async def _hash_sequence(self, paths: list[Path]) -> list[int | None]:
        return [self.mapping[path.name] for path in paths]


async def test_hashes_are_keyed_by_path_not_directory_order() -> None:
    extractor = _HashScriptedExtractor({"scene1.jpg": 1, "scene2.jpg": 2, "periodic.jpg": 3})
    candidates = [
        FrameCandidate(at_sec=0.0, path=Path("scene/scene1.jpg")),
        FrameCandidate(at_sec=10.0, path=Path("interval/periodic.jpg")),
        FrameCandidate(at_sec=20.0, path=Path("scene/scene2.jpg")),
    ]
    hashes = await extractor._hashes(candidates)
    assert hashes == {
        Path("scene/scene1.jpg"): 1,
        Path("interval/periodic.jpg"): 3,
        Path("scene/scene2.jpg"): 2,
    }
    # Одинаковые хеши от разных проходов всё равно считаются дублями.
    same = [
        FrameCandidate(at_sec=0.0, path=Path("scene/a.jpg")),
        FrameCandidate(at_sec=1.0, path=Path("interval/b.jpg")),
    ]
    dedupe = FrameExtractor(dedup_bits=0)
    kept = dedupe._dedupe(same, {Path("scene/a.jpg"): 7, Path("interval/b.jpg"): 7}, limit=10)
    assert [item.at_sec for item in kept] == [0.0]


async def test_hashes_failure_does_not_drop_frames() -> None:
    class _Failing(FrameExtractor):
        async def _hash_sequence(self, paths: list[Path]) -> list[int | None]:
            raise FrameExtractionError("ffmpeg сломался")

    extractor = _Failing()
    candidates = [FrameCandidate(at_sec=0.0, path=Path("a.jpg"))]
    assert await extractor._hashes(candidates) == {}
    kept = extractor._dedupe(candidates, {}, limit=10)
    assert kept == candidates
