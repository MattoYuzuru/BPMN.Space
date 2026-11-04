"""OCR сканов, производные узлы видео и плеер (RFC-0006, шаги 4–5) — без сети и без ffmpeg.

Проверяются: производный узел OCR по `unreadable_pages` с обновлением предупреждений и
стоимостью, отказ без модели → технический вопрос, частичный OCR → остаток страниц; кадры,
описание экрана, общая лента и краткое содержание записи; удаление кадров вместе с записью;
HTTP Range (`200`/`206`/`416`/`304`), отрезки таймкодов и оценка обработки через API.
"""

import asyncio
import io
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app.domain.capabilities import Capability
from app.domain.models import (
    MediaInfo,
    Project,
    Source,
    SourceDerivation,
    SourceKind,
    SourceOrigin,
    SourceStatus,
    SourceTrust,
)
from app.domain.sources import derivation_frame_keys
from app.infra.repositories.memory import InMemoryStore
from app.infra.storage import InMemoryFileStorage
from app.llm.base import record_usage
from app.llm.capabilities import ModelCapabilities, ModelPrices
from app.llm.client import LlmAuthError
from app.llm.multimodal import prompt_data
from app.services.common import Runtime
from app.services.media_derivation import MediaDerivationService
from tests.conftest import API, create_project

PRICES = ModelPrices(
    input=3.0,
    output=15.0,
    cache_read=0.3,
    cache_write=3.75,
    checked_on=date(2026, 11, 4),
)
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


class FakeModel:
    """Мультимодальная модель без сети: ответы по JSON-данным промпта и учёт токенов."""

    provider = "anthropic"
    model = "claude-sonnet-5-5"

    def __init__(
        self,
        *,
        vision: bool = True,
        pdf_input: bool = True,
        document_error: Exception | None = None,
        vision_error: Exception | None = None,
        summary: str = "Краткое содержание: обсудили заявку и согласование.",
    ) -> None:
        self.capabilities = ModelCapabilities(
            vision=vision, pdf_input=pdf_input, prices=PRICES, known=True
        )
        self.document_error = document_error
        self.vision_error = vision_error
        self.summary = summary
        self.document_calls: list[dict[str, Any]] = []
        self.vision_calls: list[dict[str, Any]] = []
        self.text_calls: list[str] = []
        self.released = 0

    @staticmethod
    def _data(user: str) -> dict[str, Any]:
        raw = prompt_data(user) or "{}"
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    async def complete_document(
        self, system: str, user: str, *, document: Any, json_mode: bool, max_tokens: int
    ) -> str:
        self.document_calls.append({"bytes": len(document.data), "max_tokens": max_tokens})
        if self.document_error is not None:
            raise self.document_error
        record_usage(tokens_in=1_000, tokens_out=500)
        pages = self._data(user).get("pages") or [1]
        return json.dumps({"pages": {str(page): f"Текст страницы {page}" for page in pages}})

    async def complete_vision(
        self,
        system: str,
        user: str,
        *,
        images: Any,
        json_mode: bool,
        max_tokens: int,
    ) -> str:
        self.vision_calls.append({"images": len(images), "max_tokens": max_tokens})
        if self.vision_error is not None:
            raise self.vision_error
        record_usage(tokens_in=2_000, tokens_out=400)
        frames = self._data(user).get("frames") or []
        return json.dumps(
            {
                "frames": [
                    {
                        "index": frame.get("index"),
                        "timecode": frame.get("timecode"),
                        "screen": f"Экран: открыт список заявок ({frame.get('timecode')})",
                        "text": None,
                    }
                    for frame in frames
                ]
            },
            ensure_ascii=False,
        )

    async def complete_text(self, system: str, user: str, *, max_tokens: int | None = None) -> str:
        self.text_calls.append(user)
        record_usage(tokens_in=3_000, tokens_out=300)
        return self.summary

    async def release(self) -> None:
        self.released += 1


class FakeResolver:
    def __init__(self, model: FakeModel | None) -> None:
        self.model = model
        self.requests: list[bool] = []

    async def resolve_media(
        self, user_id: UUID | None, *, need_pdf: bool, allow_mock: bool = True
    ) -> FakeModel | None:
        self.requests.append(need_pdf)
        return self.model


class FakeSink:
    def __init__(self) -> None:
        self.incidents: list[Any] = []

    async def report(self, incident: Any) -> None:
        self.incidents.append(incident)


class FakeFrames:
    """Кадры без ffmpeg: width нужен для derivation, extract возвращает заданные кадры."""

    width = 768

    def __init__(self, frames: list[Any]) -> None:
        self.frames = frames

    async def extract(self, source: Path, profile: Any) -> list[Any]:
        return self.frames


from app.ingest.frames import ExtractedFrame  # noqa: E402 — фикстура кадров


async def _repos() -> tuple[Any, Project, Runtime]:
    repos = InMemoryStore().repositories()
    runtime = Runtime()
    project = Project(
        id=runtime.new_id(),
        title="Процесс",
        description=None,
        created_at=runtime.clock(),
        updated_at=runtime.clock(),
    )
    await repos.projects.add(project)
    return repos, project, runtime


def _pdf_bytes(pages: int = 3) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


async def _pdf_source(
    repos: Any,
    storage: InMemoryFileStorage,
    project: Project,
    runtime: Runtime,
    *,
    unreadable_pages: list[int],
    pdf_pages: int = 3,
) -> Source:
    data = _pdf_bytes(pdf_pages)
    key = await storage.save(project_id=project.id, file_name="scan.pdf", data=data)
    source = Source(
        id=runtime.new_id(),
        project_id=project.id,
        kind=SourceKind.FILE,
        title="Регламент",
        content="[Страница 2]\nТекст",
        status=SourceStatus.READY,
        active=True,
        created_at=runtime.clock(),
        file_name="scan.pdf",
        mime="application/pdf",
        size_bytes=len(data),
        file_key=key,
        warning="Нет текстового слоя на страницах: 1, 3",
        unreadable_pages=unreadable_pages,
    )
    await repos.sources.add(source)
    return source


def _service(
    repos: Any,
    storage: InMemoryFileStorage,
    runtime: Runtime,
    model: FakeModel | None,
    *,
    frames: Any = None,
    sink: FakeSink | None = None,
    ocr_pages_per_request: int = 10,
) -> MediaDerivationService:
    return MediaDerivationService(
        repos,
        storage=storage,
        runtime=runtime,
        resolver=FakeResolver(model),  # type: ignore[arg-type]
        incident_sink=sink,  # type: ignore[arg-type]
        frames=frames,
        vision_batch_size=2,
        ocr_pages_per_request=ocr_pages_per_request,
    )


# --- OCR сканов ---------------------------------------------------------------------------


async def test_ocr_creates_derived_source_and_clears_warning() -> None:
    repos, project, runtime = await _repos()
    storage = InMemoryFileStorage()
    source = await _pdf_source(repos, storage, project, runtime, unreadable_pages=[1, 3])
    model = FakeModel()
    sink = FakeSink()
    service = _service(repos, storage, runtime, model, sink=sink)

    node = await service.prepare_ocr(source, initiator_id=None)
    assert node is not None
    assert node.status is SourceStatus.PROCESSING
    assert node.parent_id == source.id
    assert node.origin is SourceOrigin.DERIVED
    assert node.trust is SourceTrust.EXTRACTED
    assert node.derivation is not None
    assert node.derivation.capability == "ocr"

    await service.run_ocr(source.id, node.id, initiator_id=None)
    finished = await repos.sources.get(node.id)
    parent = await repos.sources.get(source.id)
    assert finished is not None
    assert finished.status is SourceStatus.READY
    assert "[Страница 1]" in finished.content
    assert "[Страница 3]" in finished.content
    assert finished.derivation is not None
    assert finished.derivation.provider == "anthropic"
    assert finished.derivation.model == "claude-sonnet-5-5"
    assert finished.derivation.params["pages"] == [1, 3]
    assert finished.derivation.cost_usd == pytest.approx(0.0105)
    assert parent is not None
    assert parent.unreadable_pages == []
    assert parent.warning is None
    assert sink.incidents == []


async def test_ocr_without_pdf_capable_model_reports_incident() -> None:
    repos, project, runtime = await _repos()
    storage = InMemoryFileStorage()
    source = await _pdf_source(repos, storage, project, runtime, unreadable_pages=[1, 3])
    sink = FakeSink()
    service = _service(repos, storage, runtime, None, sink=sink)

    node = await service.prepare_ocr(source, initiator_id=None)
    assert node is None
    assert len(sink.incidents) == 1
    incident = sink.incidents[0]
    assert incident.capability is Capability.OCR
    assert incident.reason == "capability_missing"
    assert "сканы" in incident.message
    assert source.unreadable_pages  # источник по-прежнему честно помечен


async def test_ocr_partial_failure_keeps_remaining_pages_and_incident() -> None:
    repos, project, runtime = await _repos()
    storage = InMemoryFileStorage()
    source = await _pdf_source(repos, storage, project, runtime, unreadable_pages=[1, 3])
    model = FakeModel(document_error=LlmAuthError("ключ отклонён"))
    sink = FakeSink()
    service = _service(repos, storage, runtime, model, sink=sink, ocr_pages_per_request=1)

    node = await service.prepare_ocr(source, initiator_id=None)
    assert node is not None
    await service.run_ocr(source.id, node.id, initiator_id=None)
    finished = await repos.sources.get(node.id)
    parent = await repos.sources.get(source.id)
    assert finished is not None
    assert finished.status is SourceStatus.FAILED
    assert parent is not None
    assert parent.unreadable_pages == [1, 3]
    assert "не распознаны" in (parent.warning or "")
    assert len(sink.incidents) == 1
    assert sink.incidents[0].reason == "auth"


# --- производные узлы видео ---------------------------------------------------------------


async def _media_source(
    repos: Any, storage: InMemoryFileStorage, project: Project, runtime: Runtime
) -> tuple[Source, Source]:
    key = await storage.save(project_id=project.id, file_name="demo.mp4", data=b"video-bytes")
    source = Source(
        id=runtime.new_id(),
        project_id=project.id,
        kind=SourceKind.FILE,
        title="Демо",
        content="",
        status=SourceStatus.READY,
        active=True,
        created_at=runtime.clock(),
        file_name="demo.mp4",
        mime="video/mp4",
        size_bytes=11,
        file_key=key,
        duration_sec=120.0,
        media=MediaInfo(has_audio=True, has_video=True),
    )
    transcript = Source(
        id=runtime.new_id(),
        project_id=project.id,
        kind=SourceKind.TEXT,
        title="Расшифровка: Демо",
        content="[00:00] Обсудили заявку\n[01:00] Отправляем на согласование",
        status=SourceStatus.READY,
        active=True,
        created_at=runtime.clock(),
        origin=SourceOrigin.DERIVED,
        parent_id=source.id,
        trust=SourceTrust.EXTRACTED,
        derivation=SourceDerivation(
            capability="speech_to_text",
            provider="mock",
            created_at=runtime.clock(),
        ),
    )
    await repos.sources.add(source)
    await repos.sources.add(transcript)
    return source, transcript


def _frames() -> list[ExtractedFrame]:
    return [
        ExtractedFrame(index=1, at_sec=0.0, data=b"\xff\xd8one"),
        ExtractedFrame(index=2, at_sec=60.0, data=b"\xff\xd8two"),
        ExtractedFrame(index=3, at_sec=90.0, data=b"\xff\xd8three"),
    ]


async def _all_sources(repos: Any, project: Project) -> list[Source]:
    return await repos.sources.list_by_project(project.id)


async def test_video_derivation_creates_all_nodes() -> None:
    repos, project, runtime = await _repos()
    storage = InMemoryFileStorage()
    source, transcript = await _media_source(repos, storage, project, runtime)
    model = FakeModel()
    sink = FakeSink()
    frames = FakeFrames(_frames())
    service = _service(repos, storage, runtime, model, frames=frames, sink=sink)

    await service.derive_media(source, transcript, profile_name="sparse", initiator_id=None)
    created = await _all_sources(repos, project)
    nodes = {node.derivation.capability: node for node in created if node.derivation is not None}
    assert "frames" in nodes
    assert "Ключевые кадры" in nodes["frames"].title
    key_frames = nodes["frames"]
    assert key_frames.trust is SourceTrust.OBSERVED
    assert key_frames.derivation is not None
    assert key_frames.derivation.capability == "frames"
    assert key_frames.derivation.provider == "ffmpeg"
    assert len(key_frames.derivation.params["frames"]) == 3
    assert "[01:00] кадр 2" in key_frames.content
    for item in key_frames.derivation.params["frames"]:
        assert await storage.load(item["key"]) == _frames()[item["index"] - 1].data

    screen = nodes["vision"]
    assert screen.trust is SourceTrust.OBSERVED
    assert screen.derivation is not None
    assert screen.derivation.capability == "vision"
    assert screen.derivation.cost_usd == pytest.approx(0.024)
    assert "[01:00] Экран" in screen.content

    feed = nodes["media_feed"]
    assert feed.trust is SourceTrust.OBSERVED
    assert "речь: Обсудили заявку" in feed.content
    assert "экран: Экран: открыт список заявок" in feed.content
    assert feed.derivation is not None
    assert feed.derivation.provider == "code"

    summary = next(node for node in created if node.trust is SourceTrust.SUMMARY)
    assert summary.derivation is not None
    assert summary.derivation.model == "claude-sonnet-5-5"
    assert summary.derivation.cost_usd == pytest.approx(0.0135)
    assert not summary.feeds_model, "краткое содержание не идёт в контекст модели"
    assert model.released >= 1
    assert sink.incidents == []


async def test_video_derivation_without_vision_model_keeps_frames_and_asks() -> None:
    repos, project, runtime = await _repos()
    storage = InMemoryFileStorage()
    source, transcript = await _media_source(repos, storage, project, runtime)
    sink = FakeSink()
    service = _service(repos, storage, runtime, None, frames=FakeFrames(_frames()), sink=sink)

    await service.derive_media(source, transcript, profile_name="detailed", initiator_id=None)
    nodes = await _all_sources(repos, project)
    capabilities = {node.derivation.capability for node in nodes if node.derivation is not None}
    assert "frames" in capabilities
    assert "vision" not in capabilities
    assert len(sink.incidents) == 1
    assert sink.incidents[0].capability is Capability.VISION
    assert sink.incidents[0].reason == "capability_missing"
    parent = await repos.sources.get(source.id)
    assert parent is not None
    assert "описание экрана" in (parent.warning or "").lower()


async def test_video_derivation_audio_profile_does_nothing() -> None:
    repos, project, runtime = await _repos()
    storage = InMemoryFileStorage()
    source, transcript = await _media_source(repos, storage, project, runtime)
    service = _service(repos, storage, runtime, FakeModel(), frames=FakeFrames(_frames()))
    before = len(await _all_sources(repos, project))
    await service.derive_media(source, transcript, profile_name="audio", initiator_id=None)
    assert len(await _all_sources(repos, project)) == before


async def test_frames_removed_with_source() -> None:
    repos, project, runtime = await _repos()
    storage = InMemoryFileStorage()
    source, _ = await _media_source(repos, storage, project, runtime)
    key = await storage.save(project_id=project.id, file_name="frame_00001.jpg", data=b"jpeg")
    node = Source(
        id=runtime.new_id(),
        project_id=project.id,
        kind=SourceKind.TEXT,
        title="Ключевые кадры: Демо",
        content="[00:00] кадр 1",
        status=SourceStatus.READY,
        active=True,
        created_at=runtime.clock(),
        origin=SourceOrigin.DERIVED,
        parent_id=source.id,
        trust=SourceTrust.OBSERVED,
        derivation=SourceDerivation(
            capability="frames",
            provider="ffmpeg",
            created_at=runtime.clock(),
            params={"frames": [{"index": 1, "at_sec": 0.0, "key": key}]},
        ),
    )
    await repos.sources.add(node)
    assert derivation_frame_keys(node) == [key]


# --- HTTP: оценка, плеер, отрезки ---------------------------------------------------------


def _add_media_source(container: Any, project_id: str, data: bytes = b"0123456789") -> str:
    async def run() -> str:
        storage = container.storage
        key = await storage.save(project_id=UUID(project_id), file_name="demo.mp4", data=data)
        source = Source(
            id=uuid4(),
            project_id=UUID(project_id),
            kind=SourceKind.FILE,
            title="Демо",
            content="",
            status=SourceStatus.READY,
            active=True,
            created_at=NOW,
            file_name="demo.mp4",
            mime="video/mp4",
            size_bytes=len(data),
            file_key=key,
            duration_sec=12.0,
            media=MediaInfo(has_audio=True, has_video=True),
        )
        await container.repos.sources.add(source)
        return str(source.id)

    return asyncio.run(run())


def _add_transcript(container: Any, project_id: str, parent_id: str) -> str:
    async def run() -> str:
        transcript = Source(
            id=uuid4(),
            project_id=UUID(project_id),
            kind=SourceKind.TEXT,
            title="Расшифровка: Демо",
            content="[00:00] Первая реплика\n[00:30] Вторая реплика",
            status=SourceStatus.READY,
            active=True,
            created_at=NOW,
            origin=SourceOrigin.DERIVED,
            parent_id=UUID(parent_id),
            trust=SourceTrust.EXTRACTED,
            duration_sec=60.0,
            derivation=SourceDerivation(
                capability="speech_to_text", provider="mock", created_at=NOW
            ),
        )
        await container.repos.sources.add(transcript)
        return str(transcript.id)

    return asyncio.run(run())


def _add_pdf_source(container: Any, project_id: str, *, unreadable: list[int]) -> str:
    async def run() -> str:
        data = _pdf_bytes(3)
        key = await container.storage.save(
            project_id=UUID(project_id), file_name="scan.pdf", data=data
        )
        source = Source(
            id=uuid4(),
            project_id=UUID(project_id),
            kind=SourceKind.FILE,
            title="Регламент",
            content="[Страница 2]\nТекст",
            status=SourceStatus.READY,
            active=True,
            created_at=NOW,
            file_name="scan.pdf",
            mime="application/pdf",
            size_bytes=len(data),
            file_key=key,
            unreadable_pages=unreadable,
            warning="Нет текстового слоя на страницах: 1, 3",
        )
        await container.repos.sources.add(source)
        return str(source.id)

    return asyncio.run(run())


def test_ocr_retry_endpoint_runs_ocr_and_clears_pages(client: TestClient, container: Any) -> None:
    project_id = create_project(client)
    source_id = _add_pdf_source(container, project_id, unreadable=[1, 3])
    started = client.post(f"{API}/sources/{source_id}/ocr")
    assert started.status_code == 202, started.text
    node = started.json()
    assert node["parent_id"] == source_id
    assert node["derivation"]["capability"] == "ocr"
    detail = client.get(f"{API}/projects/{project_id}").json()
    ocr = next(item for item in detail["sources"] if item["id"] == node["id"])
    assert ocr["status"] == "ready"
    assert "[Страница 1]" in ocr["content"]
    parent = next(item for item in detail["sources"] if item["id"] == source_id)
    assert parent["unreadable_pages"] == []
    assert parent["warning"] is None
    # Повторять нечего: все страницы уже распознаны.
    assert client.post(f"{API}/sources/{source_id}/ocr").status_code == 409


def test_media_estimate_endpoint(client: TestClient) -> None:
    project_id = create_project(client)
    response = client.post(
        f"{API}/projects/{project_id}/sources/media/estimate",
        json={"duration_sec": 600, "has_video": True, "media_profile": "sparse"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["stt"]["minutes"] == 10.0
    assert body["media_profile"] == "sparse"
    assert body["frames"]["count_max"] > 0
    assert body["total_cost_usd"]["min_usd"] is not None
    assert body["currency"] == "USD"
    audio = client.post(
        f"{API}/projects/{project_id}/sources/media/estimate",
        json={"duration_sec": 60, "has_video": True, "media_profile": "audio"},
    ).json()
    assert audio["frames"]["count_max"] == 0
    invalid = client.post(
        f"{API}/projects/{project_id}/sources/media/estimate",
        json={"duration_sec": 60, "media_profile": "unknown"},
    )
    assert invalid.status_code == 422


def test_media_stream_supports_range_and_cache(client: TestClient, container: Any) -> None:
    project_id = create_project(client)
    source_id = _add_media_source(container, project_id)
    full = client.get(f"{API}/sources/{source_id}/media")
    assert full.status_code == 200
    assert full.content == b"0123456789"
    assert full.headers["accept-ranges"] == "bytes"
    assert full.headers["content-type"].startswith("video/mp4")
    etag = full.headers["etag"]

    partial = client.get(f"{API}/sources/{source_id}/media", headers={"Range": "bytes=2-5"})
    assert partial.status_code == 206
    assert partial.content == b"2345"
    assert partial.headers["content-range"] == "bytes 2-5/10"
    assert partial.headers["content-length"] == "4"

    suffix = client.get(f"{API}/sources/{source_id}/media", headers={"Range": "bytes=-3"})
    assert suffix.status_code == 206
    assert suffix.content == b"789"

    open_ended = client.get(f"{API}/sources/{source_id}/media", headers={"Range": "bytes=7-"})
    assert open_ended.status_code == 206
    assert open_ended.content == b"789"

    beyond = client.get(f"{API}/sources/{source_id}/media", headers={"Range": "bytes=90-"})
    assert beyond.status_code == 416
    assert beyond.headers["content-range"] == "bytes */10"

    invalid = client.get(f"{API}/sources/{source_id}/media", headers={"Range": "pages=1-2"})
    assert invalid.status_code == 416

    cached = client.get(f"{API}/sources/{source_id}/media", headers={"If-None-Match": etag})
    assert cached.status_code == 304
    not_modified = client.get(
        f"{API}/sources/{source_id}/media",
        headers={"If-Modified-Since": "Wed, 04 Nov 2026 12:00:00 GMT"},
    )
    assert not_modified.status_code == 304


def test_media_stream_hides_non_media_and_unknown(client: TestClient, container: Any) -> None:
    project_id = create_project(client)
    assert client.get(f"{API}/sources/{uuid4()}/media").status_code == 404
    text_payload = client.post(
        f"{API}/projects/{project_id}/sources/text",
        json={"content": "Просто текст"},
    ).json()
    assert client.get(f"{API}/sources/{text_payload['id']}/media").status_code == 404


def test_segments_endpoint_returns_timecodes(client: TestClient, container: Any) -> None:
    project_id = create_project(client)
    source_id = _add_media_source(container, project_id)
    transcript_id = _add_transcript(container, project_id, source_id)
    response = client.get(f"{API}/sources/{source_id}/segments")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["transcript_id"] == transcript_id
    assert body["segments"][0] == {
        "start_sec": 0.0,
        "end_sec": 30.0,
        "text": "Первая реплика",
        "speaker": None,
    }
    assert body["segments"][1]["end_sec"] == 60.0
    missing = client.get(f"{API}/sources/{uuid4()}/segments")
    assert missing.status_code == 404
    text_payload = client.post(
        f"{API}/projects/{project_id}/sources/text", json={"content": "Без записи"}
    ).json()
    assert client.get(f"{API}/sources/{text_payload['id']}/segments").status_code == 409
