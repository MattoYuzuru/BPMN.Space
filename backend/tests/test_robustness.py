"""Устойчивость: единица работы, конфликты ручной правки, лимиты загрузок, разбор документов."""

import asyncio
import io
import zipfile
from collections.abc import Iterator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app.config import Settings
from app.container import Container, build_container
from app.domain.models import RunMode, RunStage, SourceKind, SourceStatus
from app.fixtures import read_bpmn
from app.infra.repositories.memory import InMemoryStore
from app.ingest.parsers import DocumentParseError, LocalDocumentParser, _pdf_text
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
    await service_container.runs.start(project_id, mode=RunMode.BUILD)

    with pytest.raises(ConflictError, match="идёт прогон"):
        await service_container.versions.save_manual(project_id, xml=xml)
    assert await service_container.versions.list(project_id) == []

    gate.set()
    await service_container.spawner.wait_idle()
    saved = await service_container.versions.save_manual(project_id, xml=xml)
    assert saved.number == 2  # версия 1 собрана прогоном


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
        f"{API}/projects/{project_id}/diagram", json={"xml": read_bpmn("tp861_v2")}
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
    await service_container.runs.start(project_id, mode=RunMode.BUILD)
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
        yield b'"}'

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
        f"{API}/projects/{project_id}/diagram", json={"xml": "<a>" + "x" * 5000 + "</a>"}
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


async def test_docx_and_csv_parse_off_loop() -> None:
    parser = LocalDocumentParser()
    assert await parser.parse(file_name="a.docx", data=_docx("Привет")) == "Привет"
    assert "Строка 1" in await parser.parse(file_name="a.csv", data=b"a,b\n1,2\n")
