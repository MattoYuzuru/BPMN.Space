"""Устойчивость: единица работы, конфликты ручной правки, лимиты загрузок, разбор документов."""

import asyncio
import hashlib
import io
import json
import time
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime
from email.message import Message
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app.config import Settings
from app.container import Container, build_container
from app.domain.analysis import (
    MAX_SOURCE_TEXT_CHARS,
    AnalysisResult,
    ContextSource,
    DiagramDraft,
    RunContext,
)
from app.domain.models import LlmCall, Run, RunMode, RunStage, RunStatus, SourceKind, SourceStatus
from app.domain.runs import RunEventKind
from app.fixtures import read_bpmn
from app.infra.repositories.memory import InMemoryStore
from app.ingest.context import describe_context, fit_sources
from app.ingest.parsers import DocumentParseError, LocalDocumentParser, _pdf_text
from app.llm.base import PipelineError, record_usage, run_deadline, track_usage
from app.llm.openai_compatible import DeepSeekPipeline
from app.main import create_app
from app.services.errors import ConflictError, InvalidInputError, NotFoundError
from tests.conftest import API, create_project

_WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _docx(text: str = "Принять заявку") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "word/document.xml",
            f'<w:document xmlns:w="{_WORD_NS}"><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p>'
            "</w:body></w:document>",
        )
    return buffer.getvalue()


def _pdf(pages: int) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=100, height=100)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.fixture
def service_container() -> Container:
    return build_container(Settings(mock_delay_scale=0, seed_demo_data=False))


async def _project_with_text(container: Container) -> UUID:
    view = await container.projects.create(title="Процесс", description=None)
    await container.sources.create_text(
        view.project.id,
        content="1. Принять заявку. Ответственный: оператор.",
        title=None,
        kind=SourceKind.TEXT,
        duration_sec=None,
    )
    return view.project.id


# ---------- ручная правка и прогон ----------


async def test_manual_save_during_active_run_is_conflict(service_container: Container) -> None:
    gate = asyncio.Event()

    async def hold(stage: RunStage) -> None:
        if stage is RunStage.READING_SOURCES:
            await gate.wait()

    service_container.runs._pace = hold
    project_id = await _project_with_text(service_container)
    xml = read_bpmn("tp861_v2")
    await service_container.runs.start(project_id, mode=RunMode.BUILD, created_by=None)

    with pytest.raises(ConflictError, match="идёт сборка"):
        await service_container.versions.save_manual(project_id, xml=xml)
    assert await service_container.versions.list(project_id) == []

    gate.set()
    await service_container.spawner.wait_idle()
    latest = (await service_container.versions.list(project_id))[0]
    saved = await service_container.versions.save_manual(
        project_id, xml=xml, base_version_id=latest.id
    )
    assert saved.number == 2  # версия 1 собрана прогоном


async def test_manual_save_during_active_analyze_run_is_allowed(
    service_container: Container,
) -> None:
    gate = asyncio.Event()

    async def hold(stage: RunStage) -> None:
        if stage is RunStage.READING_SOURCES:
            await gate.wait()

    service_container.runs._pace = hold
    project_id = await _project_with_text(service_container)
    await service_container.runs.start(project_id, mode=RunMode.ANALYZE, created_by=None)

    saved = await service_container.versions.save_manual(project_id, xml=read_bpmn("tp861_v2"))
    assert saved.number == 1  # анализ версий не создаёт, правка ему не мешает

    gate.set()
    await service_container.spawner.wait_idle()


async def test_manual_save_unknown_project_is_not_found(service_container: Container) -> None:
    with pytest.raises(NotFoundError):
        await service_container.versions.save_manual(UUID(int=1), xml=read_bpmn("tp861_v2"))


def test_manual_save_conflict_is_http_409(client: TestClient, container: Container) -> None:
    project_id = create_project(client)
    client.post(f"{API}/projects/{project_id}/sources/text", json={"content": "Шаг один."})
    gate = asyncio.Event()

    async def hold(_stage: RunStage) -> None:
        await gate.wait()

    container.runs._pace = hold
    assert (
        client.post(f"{API}/projects/{project_id}/runs", json={"mode": "build"}).status_code == 202
    )
    response = client.put(
        f"{API}/projects/{project_id}/diagram",
        json={"xml": read_bpmn("tp861_v2"), "base_version_id": None},
    )
    assert response.status_code == 409
    assert "дождитесь" in response.json()["detail"]


# ---------- точечные обновления источников ----------


async def test_process_file_keeps_title_and_active_changed_while_parsing(
    service_container: Container,
) -> None:
    sources = service_container.sources
    view = await service_container.projects.create(title="Файлы", description=None)
    source, slow = await sources.create_file(
        view.project.id, file_name="reg.docx", mime=None, data=_docx(), title=None
    )
    assert slow
    assert source.status is SourceStatus.PROCESSING

    renamed = await sources.update(
        source.id, title="Мой регламент", content=None, active=False, fields={"title", "active"}
    )
    assert renamed.status is SourceStatus.PROCESSING  # правка не «закрыла» разбор

    await sources.process_file(source.id)
    final = await sources.update(source.id, title=None, content=None, active=None, fields=set())
    assert final.status is SourceStatus.READY
    assert final.content == "Принять заявку"
    assert final.title == "Мой регламент"
    assert final.active is False


async def test_process_file_does_not_resurrect_deleted_source(
    service_container: Container,
) -> None:
    sources = service_container.sources
    view = await service_container.projects.create(title="Файлы", description=None)
    source, _ = await sources.create_file(
        view.project.id, file_name="reg.docx", mime=None, data=_docx(), title=None
    )
    await sources.delete(source.id)
    await sources.process_file(source.id)
    assert await service_container.repos.sources.get(source.id) is None


async def test_process_file_does_not_overwrite_manual_text(service_container: Container) -> None:
    repos = service_container.repos
    view = await service_container.projects.create(title="Файлы", description=None)
    source, _ = await service_container.sources.create_file(
        view.project.id, file_name="reg.docx", mime=None, data=_docx(), title=None
    )
    # Аналитик (или перезапуск) уже перевёл источник в failed и вписал текст.
    assert await repos.sources.patch(
        source.id, {"status": SourceStatus.READY, "content": "Вручную"}
    )
    await service_container.sources.process_file(source.id)
    stored = await repos.sources.get(source.id)
    assert stored is not None
    assert stored.content == "Вручную"


async def test_content_edit_of_processing_file_is_rejected(service_container: Container) -> None:
    view = await service_container.projects.create(title="Файлы", description=None)
    source, _ = await service_container.sources.create_file(
        view.project.id, file_name="reg.docx", mime=None, data=_docx(), title=None
    )
    with pytest.raises(InvalidInputError, match="ещё обрабатывается"):
        await service_container.sources.update(
            source.id, title=None, content="Текст", active=None, fields={"content"}
        )


async def test_content_edit_loses_race_with_parsing(service_container: Container) -> None:
    view = await service_container.projects.create(title="Файлы", description=None)
    source, _ = await service_container.sources.create_file(
        view.project.id, file_name="reg.docx", mime=None, data=_docx(), title=None
    )
    await service_container.sources.process_file(source.id)  # ready
    repos = service_container.repos
    # Источник упал в failed между чтением и записью правки → правка не должна «воскрешать» его.
    original_get = repos.sources.get
    calls = 0

    async def stale_get(source_id: UUID):
        nonlocal calls
        calls += 1
        item = await original_get(source_id)
        if calls == 1 and item is not None:
            await repos.sources.patch(source_id, {"status": SourceStatus.FAILED})
        return item

    repos.sources.get = stale_get  # type: ignore[method-assign]
    with pytest.raises(ConflictError, match="только что изменился"):
        await service_container.sources.update(
            source.id, title=None, content="Новый", active=None, fields={"content"}
        )


async def test_memory_source_patch_rejects_unknown_fields(service_container: Container) -> None:
    project_id = await _project_with_text(service_container)
    source = (await service_container.repos.sources.list_by_project(project_id))[0]
    with pytest.raises(ValueError, match="нельзя менять точечно"):
        await service_container.repos.sources.patch(source.id, {"project_id": project_id})
    assert not await service_container.repos.sources.patch(UUID(int=5), {"active": False})
    assert await service_container.repos.sources.fail_processing("x") == 0


# ---------- удаление проекта ----------


async def test_memory_project_delete_removes_everything(service_container: Container) -> None:
    project_id = await _project_with_text(service_container)
    await service_container.runs.start(project_id, mode=RunMode.BUILD, created_by=None)
    await service_container.spawner.wait_idle()
    store = _store(service_container)
    assert all([store.runs, store.versions, store.llm_calls])
    await service_container.projects.delete(project_id)
    assert not any([store.sources, store.runs, store.versions, store.questions, store.llm_calls])
    with pytest.raises(NotFoundError):
        await service_container.projects.delete(project_id)


def _store(container: Container) -> InMemoryStore:
    return container.repos.projects._store  # type: ignore[attr-defined]


# ---------- лимиты загрузок ----------


@pytest.fixture
def small_client() -> Iterator[TestClient]:
    settings = Settings(
        mock_delay_scale=0,
        seed_demo_data=False,
        auth_enabled=False,
        rate_limit_enabled=False,
        max_upload_bytes=1024,
        max_audio_bytes=2048,
        max_diagram_bytes=1024,
    )
    with TestClient(create_app(settings, container=build_container(settings))) as client:
        yield client


def test_oversized_upload_is_rejected_by_content_length(small_client: TestClient) -> None:
    project_id = create_project(small_client)
    big = b"a" * (2 * 1024 * 1024)
    response = small_client.post(
        f"{API}/projects/{project_id}/sources/file", files={"file": ("big.txt", big)}
    )
    assert response.status_code == 413
    assert response.json() == {"detail": "Файл больше 1 МБ"}


def test_upload_slightly_over_limit_is_rejected_while_reading(small_client: TestClient) -> None:
    project_id = create_project(small_client)
    response = small_client.post(
        f"{API}/projects/{project_id}/sources/file", files={"file": ("big.txt", b"a" * 5000)}
    )
    assert response.status_code == 413
    ok = small_client.post(
        f"{API}/projects/{project_id}/sources/file", files={"file": ("ok.txt", b"a" * 1000)}
    )
    assert ok.status_code == 201


def test_oversized_audio_is_rejected(small_client: TestClient) -> None:
    response = small_client.post(
        f"{API}/transcriptions",
        files={"file": ("a.webm", b"\x00" * (3 * 1024 * 1024), "audio/webm")},
    )
    assert response.status_code == 413
    assert "Запись больше" in response.json()["detail"]
    slightly = small_client.post(
        f"{API}/transcriptions", files={"file": ("a.webm", b"\x00" * 4000, "audio/webm")}
    )
    assert slightly.status_code == 413


def test_chunked_body_without_content_length_is_counted(small_client: TestClient) -> None:
    project_id = create_project(small_client)

    def body() -> Iterator[bytes]:
        yield b'{"xml": "'
        for _ in range(100):
            yield b"x" * 2048
        yield b'", "base_version_id": null}'

    response = small_client.put(
        f"{API}/projects/{project_id}/diagram",
        content=body(),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json() == {"detail": "Схема больше 1 МБ"}


def test_diagram_over_limit_is_rejected(small_client: TestClient) -> None:
    project_id = create_project(small_client)
    response = small_client.put(
        f"{API}/projects/{project_id}/diagram",
        json={"xml": "<a>" + "x" * 5000 + "</a>", "base_version_id": None},
    )
    assert response.status_code == 413


def test_normal_requests_are_not_limited(client: TestClient) -> None:
    project_id = create_project(client)
    response = client.post(
        f"{API}/projects/{project_id}/sources/text", json={"content": "Текст " * 1000}
    )
    assert response.status_code == 201


# ---------- разбор документов ----------


async def test_pdf_page_limit() -> None:
    parser = LocalDocumentParser(max_pdf_pages=2)
    with pytest.raises(DocumentParseError, match="3 страниц — больше лимита 2"):
        await parser.parse(file_name="long.pdf", data=_pdf(3))
    with pytest.raises(DocumentParseError, match="не найден текстовый слой"):
        await parser.parse(file_name="scan.pdf", data=_pdf(2))


def test_pdf_stops_at_its_deadline() -> None:
    with pytest.raises(DocumentParseError, match="слишком много времени"):
        _pdf_text(_pdf(2), max_pages=10, max_chars=1000, deadline=0.0)


async def test_parsing_timeout_does_not_block_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    import time  # noqa: PLC0415

    def slow(*_args: object, **_kwargs: object) -> str:
        time.sleep(0.5)
        return "текст"

    monkeypatch.setattr("app.ingest.parsers._pdf_text", slow)
    parser = LocalDocumentParser(timeout_sec=0.05)
    ticks = 0

    async def heartbeat() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    beat = asyncio.create_task(heartbeat())
    with pytest.raises(DocumentParseError, match="слишком много времени"):
        await parser.parse(file_name="x.pdf", data=b"%PDF")
    beat.cancel()
    assert ticks >= 2  # цикл событий жил, пока шёл разбор


async def test_parsing_uses_dedicated_executor_not_default_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading  # noqa: PLC0415

    names: list[str] = []

    def work(*_args: object, **_kwargs: object) -> str:
        names.append(threading.current_thread().name)
        return "текст"

    monkeypatch.setattr("app.ingest.parsers._pdf_text", work)
    parser = LocalDocumentParser()
    assert await parser.parse(file_name="x.pdf", data=b"%PDF") == "текст"
    assert names[0].startswith("doc-parse")


async def test_stuck_parsing_does_not_starve_default_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    release = __import__("threading").Event()

    def stuck(*_args: object, **_kwargs: object) -> str:
        release.wait(5)
        return "текст"

    monkeypatch.setattr("app.ingest.parsers._pdf_text", stuck)
    parser = LocalDocumentParser(timeout_sec=0.05)
    try:
        for _ in range(2):  # занимаем оба слота выделенного пула
            with pytest.raises(DocumentParseError, match="слишком много времени"):
                await parser.parse(file_name="x.pdf", data=b"%PDF")
        # Общий пул потоков остаётся свободным для остальной работы.
        assert await asyncio.wait_for(asyncio.to_thread(lambda: "ok"), 1) == "ok"
    finally:
        release.set()


async def test_docx_and_csv_parse_off_loop() -> None:
    parser = LocalDocumentParser()
    assert await parser.parse(file_name="a.docx", data=_docx("Привет")) == "Привет"
    assert "Строка 1" in await parser.parse(file_name="a.csv", data=b"a,b\n1,2\n")


# ---------- LLM: повторы, токены, срок, бюджет контекста ----------


class _Pipeline:
    """Конвейер-пустышка: фиксирует токены так же, как это делает адаптер провайдера."""

    model_name = "fake-model"

    def __init__(self, *, delay: float = 0.0, tokens: tuple[int, int] | None = (120, 30)) -> None:
        self.delay = delay
        self.tokens = tokens
        self.contexts: list[RunContext] = []

    async def analyze(self, context: RunContext) -> AnalysisResult:
        self.contexts.append(context)
        await asyncio.sleep(self.delay)
        if self.tokens:
            record_usage(tokens_in=self.tokens[0], tokens_out=self.tokens[1])
            record_usage(tokens_in=1, tokens_out=2)
        return AnalysisResult()

    async def structure(self, context: RunContext, analysis: AnalysisResult) -> DiagramDraft:
        await asyncio.sleep(self.delay)
        return DiagramDraft(xml=read_bpmn("tp861_v2"))


def _urlopen_response(payload: dict[str, object]) -> MagicMock:
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
    return response


_OK = {
    "choices": [{"message": {"content": "{}"}}],
    "usage": {"prompt_tokens": 100, "completion_tokens": 25},
}


def _http_error(code: int, retry_after: str | None = None) -> HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return HTTPError("https://api.example/chat", code, "err", headers, None)


def test_retry_after_is_respected_and_followed_by_success() -> None:
    sleeps: list[float] = []
    pipeline = DeepSeekPipeline(api_key="k", sleep=sleeps.append, jitter=lambda: 0.0)
    with patch(
        "app.llm.openai_compatible.urlopen",
        side_effect=[_http_error(429, "7"), _urlopen_response(_OK)],
    ) as urlopen:
        assert pipeline._request_json("s", "p") == "{}"
    assert urlopen.call_count == 2
    assert sleeps == [7.0]  # Retry-After больше собственной паузы (0.5 с)


@pytest.mark.parametrize("code", [408, 429, 500, 502, 503, 504])
def test_transient_http_errors_are_retried_with_bound(code: int) -> None:
    sleeps: list[float] = []
    pipeline = DeepSeekPipeline(api_key="k", max_retries=2, sleep=sleeps.append, jitter=lambda: 1.0)
    with (
        patch(
            "app.llm.openai_compatible.urlopen",
            side_effect=lambda *_a, **_k: _raise(_http_error(code)),
        ),
        pytest.raises(RuntimeError, match=f"HTTP {code}"),
    ):
        pipeline._request_json("s", "p")
    assert sleeps == [1.0, 2.0]  # полный джиттер: потолок удваивается


def _raise(error: Exception) -> None:
    raise error


@pytest.mark.parametrize("code", [400, 401, 402, 404, 422])
def test_client_errors_are_not_retried(code: int) -> None:
    sleeps: list[float] = []
    pipeline = DeepSeekPipeline(api_key="k", sleep=sleeps.append)
    with (
        patch("app.llm.openai_compatible.urlopen", side_effect=_http_error(code)) as urlopen,
        pytest.raises(RuntimeError, match=f"HTTP {code}"),
    ):
        pipeline._request_json("s", "p")
    assert urlopen.call_count == 1
    assert sleeps == []


def test_backoff_is_bounded_and_jittered() -> None:
    low = DeepSeekPipeline(api_key="k", retry_base_sec=1, retry_max_sec=10, jitter=lambda: 0.0)
    high = DeepSeekPipeline(api_key="k", retry_base_sec=1, retry_max_sec=10, jitter=lambda: 1.0)
    assert [low._retry_delay(n, None) for n in range(6)] == [0.5, 1.0, 2.0, 4.0, 5.0, 5.0]
    assert [high._retry_delay(n, None) for n in range(6)] == [1.0, 2.0, 4.0, 8.0, 10.0, 10.0]
    assert high._retry_delay(0, 1000.0) == 30.0  # Retry-After тоже ограничен


def test_retry_after_with_a_date_is_ignored() -> None:
    sleeps: list[float] = []
    pipeline = DeepSeekPipeline(api_key="k", sleep=sleeps.append, jitter=lambda: 0.0)
    with patch(
        "app.llm.openai_compatible.urlopen",
        side_effect=[_http_error(503, "Wed, 21 Oct 2026 07:28:00 GMT"), _urlopen_response(_OK)],
    ):
        pipeline._request_json("s", "p")
    assert sleeps == [0.5]


def test_token_usage_is_recorded_from_provider() -> None:
    pipeline = DeepSeekPipeline(api_key="k", sleep=_NO_SLEEP_FN)
    with (
        track_usage() as usage,
        patch("app.llm.openai_compatible.urlopen", return_value=_urlopen_response(_OK)),
    ):
        pipeline._request_json("s", "p")
        pipeline._request_json("s", "p")
    assert (usage.tokens_in, usage.tokens_out, usage.requests) == (200, 50, 2)
    # Без блока учёта и с кривым usage ничего не ломается.
    broken = {"choices": [{"message": {"content": "{}"}}], "usage": {"prompt_tokens": "много"}}
    with (
        track_usage() as other,
        patch("app.llm.openai_compatible.urlopen", return_value=_urlopen_response(broken)),
    ):
        pipeline._request_json("s", "p")
    assert (other.tokens_in, other.tokens_out) == (0, 0)


_NO_SLEEP_FN = lambda _seconds: None  # noqa: E731


def test_retry_is_skipped_when_run_deadline_would_pass() -> None:
    sleeps: list[float] = []
    pipeline = DeepSeekPipeline(api_key="k", sleep=sleeps.append, jitter=lambda: 1.0)
    with (
        run_deadline(0.5),  # паузы 1 с не помещаются в оставшиеся полсекунды
        patch("app.llm.openai_compatible.urlopen", side_effect=_http_error(503)) as urlopen,
        pytest.raises(RuntimeError, match="HTTP 503"),
    ):
        pipeline._request_json("s", "p")
    assert urlopen.call_count == 1
    assert sleeps == []


def test_request_timeout_is_cut_to_the_run_deadline() -> None:
    pipeline = DeepSeekPipeline(api_key="k", timeout_sec=120)
    with (
        run_deadline(5),
        patch("app.llm.openai_compatible.urlopen", return_value=_urlopen_response(_OK)) as m,
    ):
        pipeline._request_json("s", "p")
    assert m.call_args.kwargs["timeout"] <= 5
    with run_deadline(1e-9):
        time.sleep(0.001)
        with pytest.raises(RuntimeError, match="не уложился"):
            pipeline._request_json("s", "p")


async def test_no_new_model_request_after_deadline() -> None:
    calls = 0

    def complete(_system: str, _prompt: str) -> str:
        nonlocal calls
        calls += 1
        return "{}"

    pipeline = DeepSeekPipeline(api_key="k", complete=complete)
    context = RunContext(project_id=uuid4(), project_title="П", sources=[], questions=[])
    with run_deadline(1e-9):
        await asyncio.sleep(0.001)
        with pytest.raises(PipelineError, match="не уложился"):
            await pipeline.analyze(context)
    assert calls == 0


# ---------- RunService: токены, компактный запрос, срок, done при сбое ----------


async def _run_to_end(container: Container, project_id: UUID, mode: RunMode = RunMode.BUILD):
    run = await container.runs.start(project_id, mode=mode, created_by=None)
    await container.spawner.wait_idle()
    return run, [e async for e in await container.runs.events(run.id)]


def _llm_calls(container: Container) -> list[LlmCall]:
    return list(_store(container).llm_calls.values())


async def test_tokens_and_compact_request_are_saved(service_container: Container) -> None:
    pipeline = _Pipeline()
    service_container.runs._pipeline = pipeline
    view = await service_container.projects.create(title="Процесс", description=None)
    project_id = view.project.id
    text = "1. Принять заявку. Ответственный: оператор."
    await service_container.sources.create_text(
        project_id, content=text, title="Регламент", kind=SourceKind.TEXT, duration_sec=None
    )

    run, _ = await _run_to_end(service_container, project_id)

    calls = {c.stage: c for c in _llm_calls(service_container)}
    assert (calls["analyze"].tokens_in, calls["analyze"].tokens_out) == (121, 32)
    assert calls["structure"].tokens_in is None  # провайдер токены не сообщил
    request = calls["analyze"].request["context"]
    assert text not in json.dumps(calls["analyze"].request, ensure_ascii=False)
    (source,) = request["sources"]
    assert source["chars"] == len(text)
    assert source["sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert request["current_xml"] is None
    assert (await service_container.runs.get(run.id)).status is RunStatus.SUCCEEDED


async def test_context_trimming_is_reported_in_run_warnings() -> None:
    settings = Settings(mock_delay_scale=0, seed_demo_data=False, llm_context_budget_chars=4000)
    container = build_container(settings)
    pipeline = _Pipeline()
    container.runs._pipeline = pipeline
    view = await container.projects.create(title="Большой", description=None)
    for name in ("Первый", "Второй"):
        await container.sources.create_text(
            view.project.id,
            content="слово " * 1000,
            title=name,
            kind=SourceKind.TEXT,
            duration_sec=None,
        )

    run, events = await _run_to_end(container, view.project.id, RunMode.ANALYZE)

    seen = pipeline.contexts[0]
    assert sum(len(s.content) for s in seen.sources) <= 4000
    stored = await container.runs.get(run.id)
    assert len(stored.warnings) == 1
    assert "обрезаны 2 из 2" in stored.warnings[0]
    done = events[-1].payload
    assert isinstance(done, Run)
    assert done.warnings == stored.warnings


def test_run_warnings_are_part_of_the_api(client: TestClient) -> None:
    project_id = create_project(client)
    client.post(f"{API}/projects/{project_id}/sources/text", json={"content": "Шаг один."})
    run = client.post(f"{API}/projects/{project_id}/runs", json={"mode": "analyze"}).json()
    assert run["warnings"] == []


async def test_run_deadline_fails_the_run_and_closes_the_stream() -> None:
    settings = Settings(mock_delay_scale=0, seed_demo_data=False, run_deadline_sec=0.05)
    container = build_container(settings)
    container.runs._pipeline = _Pipeline(delay=5)
    project_id = await _project_with_text(container)

    run, events = await asyncio.wait_for(_run_to_end(container, project_id), 5)

    stored = await container.runs.get(run.id)
    assert stored.status is RunStatus.FAILED
    assert stored.error is not None
    assert "не уложился" in stored.error
    assert [e.kind for e in events][-2:] == [RunEventKind.ERROR, RunEventKind.DONE]


async def test_stream_is_closed_even_if_saving_the_failure_fails(
    service_container: Container,
) -> None:
    project_id = await _project_with_text(service_container)
    runs = service_container.repos.runs
    original_update = runs.update

    async def broken_update(run: Run) -> None:
        if run.status is RunStatus.FAILED:
            raise OSError("БД недоступна")
        await original_update(run)

    runs.update = broken_update  # type: ignore[method-assign]
    service_container.runs._pipeline = _Pipeline(tokens=None)

    async def boom(_stage: RunStage) -> None:
        raise PipelineError("модель недоступна")

    service_container.runs._pace = boom
    run = await service_container.runs.start(project_id, mode=RunMode.ANALYZE, created_by=None)
    await asyncio.wait_for(service_container.spawner.wait_idle(), 5)

    events = [e async for e in await service_container.runs.events(run.id)]
    assert [e.kind for e in events][-2:] == [RunEventKind.ERROR, RunEventKind.DONE]


async def test_stream_is_closed_if_final_save_of_a_successful_run_fails(
    service_container: Container,
) -> None:
    project_id = await _project_with_text(service_container)
    runs = service_container.repos.runs
    original_update = runs.update

    async def broken_update(run: Run) -> None:
        if run.status is RunStatus.SUCCEEDED:
            raise OSError("БД недоступна")
        await original_update(run)

    runs.update = broken_update  # type: ignore[method-assign]
    service_container.runs._pipeline = _Pipeline(tokens=None)
    run = await service_container.runs.start(project_id, mode=RunMode.ANALYZE, created_by=None)
    await asyncio.wait_for(service_container.spawner.wait_idle(), 5)

    events = [e async for e in await service_container.runs.events(run.id)]
    assert events[-1].kind is RunEventKind.DONE
    assert (await service_container.runs.get(run.id)).status is RunStatus.FAILED


async def test_done_is_published_even_if_run_read_fails(service_container: Container) -> None:
    runs = service_container.repos.runs
    run_id = uuid4()

    async def broken_get(_run_id: UUID) -> Run | None:
        raise OSError("БД недоступна")

    runs.get = broken_get  # type: ignore[method-assign]
    with pytest.raises(OSError, match="БД недоступна"):
        await service_container.runs._execute(run_id)

    events = [e async for e in service_container.runs._events.subscribe(run_id)]
    assert events[-1].kind is RunEventKind.DONE


async def test_reconcile_does_not_overwrite_answer_written_meanwhile(
    service_container: Container,
) -> None:
    project_id = await _project_with_text(service_container)
    container = service_container
    questions = container.repos.questions
    from app.domain.models import Question, QuestionKind, QuestionStatus, Severity  # noqa: PLC0415

    question = Question(
        id=uuid4(),
        project_id=project_id,
        code="Q-1",
        kind=QuestionKind.MISSING_ACTOR,
        severity=Severity.MAJOR,
        status=QuestionStatus.OPEN,
        text="Кто принимает заявку?",
        assumption="",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    await questions.add(question)
    # Аналитик отвечает после того, как сверка прочитала вопрос.
    stale = await questions.get(question.id)
    assert stale is not None
    answered = await questions.get(question.id)
    assert answered is not None
    answered.status = QuestionStatus.ANSWERED
    await questions.update(answered)

    stale.status = QuestionStatus.RESOLVED
    ok = await questions.apply_reconciled(stale, expected_status=QuestionStatus.OPEN)

    assert ok is False
    kept = await questions.get(question.id)
    assert kept is not None
    assert kept.status is QuestionStatus.ANSWERED


# ---------- бюджет контекста ----------


def _source(title: str, size: int, minute: int = 0) -> ContextSource:
    return ContextSource(
        id=uuid4(),
        kind=SourceKind.TEXT,
        title=title,
        content=("а" * (size - 1) + " ") * 1,
        created_at=datetime(2026, 1, 1, 12, minute, tzinfo=UTC),
    )


def test_sources_within_budget_are_untouched() -> None:
    sources = [_source("Один", 3000), _source("Два", 5000, 1)]
    fitted, warnings = fit_sources(sources, budget_chars=10_000)
    assert fitted == sources
    assert warnings == []


def test_budget_keeps_short_sources_whole_and_shares_the_rest() -> None:
    short, long_a, long_b = (
        _source("Короткий", 2000),
        _source("А", 30_000, 1),
        _source("Б", 30_000, 2),
    )
    fitted, warnings = fit_sources([short, long_a, long_b], budget_chars=12_000)
    sizes = [len(s.content) for s in fitted]
    assert sizes[0] == 2000
    assert sizes[1] == sizes[2] == 5000
    assert sum(sizes) <= 12_000
    assert len(warnings) == 1
    assert "обрезаны 2 из 3" in warnings[0]
    assert "«А»" in warnings[0]
    assert short.content == fitted[0].content


def test_per_source_cap_applies_even_within_budget() -> None:
    huge = _source("Огромный", MAX_SOURCE_TEXT_CHARS + 5000)
    fitted, warnings = fit_sources([huge], budget_chars=500_000)
    assert len(fitted[0].content) <= MAX_SOURCE_TEXT_CHARS
    assert warnings


def test_oldest_sources_are_dropped_when_there_are_too_many() -> None:
    sources = [_source(f"Файл {i}", 2500, i) for i in range(8)]
    fitted, warnings = fit_sources(sources, budget_chars=10_000)  # не больше 5 источников
    assert [s.title for s in fitted] == [f"Файл {i}" for i in range(3, 8)]
    assert "3 самых старых" in warnings[0]
    assert "«Файл 0»" in warnings[0]


def test_trimmed_text_is_cut_on_a_word_boundary() -> None:
    source = ContextSource(
        id=uuid4(),
        kind=SourceKind.TEXT,
        title="Т",
        content="слово " * 2000,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    (fitted,), _ = fit_sources([source], budget_chars=2500)
    assert fitted.content.endswith("слово")
    assert len(fitted.content) <= 2500


def test_describe_context_hides_text_but_keeps_identity() -> None:
    source = _source("Регламент", 100)
    context = RunContext(
        project_id=uuid4(),
        project_title="П",
        sources=[source],
        questions=[],
        current_xml="<x/>",
        warnings=["w"],
    )
    description = describe_context(context)
    assert source.content not in json.dumps(description, ensure_ascii=False)
    assert description["current_xml"]["chars"] == 4
    assert description["sources"][0]["id"] == str(source.id)
    assert description["warnings"] == ["w"]
