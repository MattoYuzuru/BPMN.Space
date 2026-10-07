"""Юнит-тесты сервисов и mock-реализаций без HTTP: семафор прогонов, шина событий, парсеры, STT."""

import asyncio
import io
import zipfile
from uuid import UUID, uuid4

import pytest

from app.config import Settings
from app.container import Container, build_container
from app.domain.models import QuestionStatus, Run, RunMode, RunStage, RunStatus, SourceKind
from app.domain.runs import RunError, RunEventKind
from app.infra.bpmn_tools import MockBpmnTools
from app.infra.events import InMemoryRunEventBus
from app.infra.seed import DEMO_PROJECT_ID, build_seed
from app.infra.storage import InMemoryFileStorage
from app.infra.tasks import AsyncioTaskSpawner
from app.ingest.parsers import (
    DocumentParseError,
    LocalDocumentParser,
    UnsupportedFormatError,
    decode_text,
)
from app.ingest.stt import MockSpeechToText
from app.services.errors import ConflictError, InvalidInputError


@pytest.fixture
def service_container() -> Container:
    return build_container(Settings(mock_delay_scale=0))


async def _new_project(container: Container) -> UUID:
    view = await container.projects.create(title="Процесс", description=None)
    await container.sources.create_text(
        view.project.id,
        content="1. Принять заявку. Ответственный: оператор.",
        title=None,
        kind=SourceKind.TEXT,
        duration_sec=None,
    )
    return view.project.id


async def test_no_more_than_two_runs_at_once(service_container: Container) -> None:
    gate = asyncio.Event()
    running: list[int] = []
    peak = 0

    async def pace(stage: RunStage) -> None:
        nonlocal peak
        if stage is RunStage.READING_SOURCES:
            running.append(1)
            peak = max(peak, len(running))
            await gate.wait()
            running.pop()

    service_container.runs._pace = pace
    projects = [await _new_project(service_container) for _ in range(3)]
    runs: list[Run] = [
        await service_container.runs.start(p, mode=RunMode.ANALYZE, created_by=None)
        for p in projects
    ]
    await asyncio.sleep(0.05)
    states = [(await service_container.runs.get(r.id)).status for r in runs]
    assert states.count(RunStatus.RUNNING) == 2
    assert states.count(RunStatus.QUEUED) == 1
    gate.set()
    await service_container.spawner.wait_idle()
    assert peak == 2
    finals = [(await service_container.runs.get(r.id)).status for r in runs]
    assert finals == [RunStatus.SUCCEEDED] * 3


async def test_shutdown_run_remains_queued_for_recovery(service_container: Container) -> None:
    async def forever(_: RunStage) -> None:
        await asyncio.sleep(3600)

    service_container.runs._pace = forever
    run = await service_container.runs.start(DEMO_PROJECT_ID, mode=RunMode.BUILD, created_by=None)
    await asyncio.sleep(0.01)
    await service_container.spawner.shutdown()
    final = await service_container.runs.get(run.id)
    assert final.status is RunStatus.QUEUED
    assert final.error is None


async def test_project_editor_can_cancel_shared_run(service_container: Container) -> None:
    entered = asyncio.Event()

    async def hold(_: RunStage) -> None:
        entered.set()
        await asyncio.sleep(3600)

    service_container.runs._pace = hold
    run = await service_container.runs.start(DEMO_PROJECT_ID, mode=RunMode.BUILD, created_by=None)
    await asyncio.wait_for(entered.wait(), timeout=1)

    cancelled = await service_container.runs.cancel(run.id)

    assert cancelled.status is RunStatus.CANCELLED
    assert cancelled.error == "Прогон отменён участником"
    events = [event async for event in await service_container.runs.events(run.id)]
    assert events[-1].kind is RunEventKind.DONE
    assert isinstance(events[-1].payload, Run)
    assert events[-1].payload.status is RunStatus.CANCELLED


async def test_queued_run_can_be_cancelled_before_it_starts(service_container: Container) -> None:
    gate = asyncio.Event()
    entered = asyncio.Event()
    service_container.runs._limit = asyncio.Semaphore(1)

    async def hold(_: RunStage) -> None:
        entered.set()
        await gate.wait()

    service_container.runs._pace = hold
    project_ids = [await _new_project(service_container) for _ in range(2)]
    running = await service_container.runs.start(
        project_ids[0], mode=RunMode.ANALYZE, created_by=None
    )
    await asyncio.wait_for(entered.wait(), timeout=1)
    queued = await service_container.runs.start(
        project_ids[1], mode=RunMode.ANALYZE, created_by=None
    )
    assert (await service_container.runs.get(queued.id)).status is RunStatus.QUEUED

    cancelled = await service_container.runs.cancel(queued.id)
    assert cancelled.status is RunStatus.CANCELLED
    assert (await service_container.runs.get(running.id)).status is RunStatus.RUNNING
    gate.set()
    await service_container.spawner.wait_idle()


async def test_unexpected_error_marks_run_failed(service_container: Container) -> None:
    async def boom(_: RunStage) -> None:
        raise RuntimeError("сбой")

    service_container.runs._pace = boom
    run = await service_container.runs.start(DEMO_PROJECT_ID, mode=RunMode.ANALYZE, created_by=None)
    await service_container.spawner.wait_idle()
    kinds = [e.kind async for e in await service_container.runs.events(run.id)]
    assert kinds[-2:] == [RunEventKind.ERROR, RunEventKind.DONE]
    final = await service_container.runs.get(run.id)
    assert final.error == "Внутренняя ошибка прогона, попробуйте ещё раз"


async def test_event_bus_delivers_history_then_live() -> None:
    bus = InMemoryRunEventBus(max_runs=2)
    run_id = uuid4()
    await bus.publish(run_id, RunEventKind.ERROR, RunError(message="первое"))
    received: list[int] = []

    async def listen() -> None:
        async for event in bus.subscribe(run_id):
            received.append(event.id)

    listener = asyncio.create_task(listen())
    await asyncio.sleep(0)
    run = Run(
        id=run_id,
        project_id=uuid4(),
        mode=RunMode.ANALYZE,
        status=RunStatus.FAILED,
        started_at=build_seed().runs[0].started_at,
    )
    await bus.publish(run_id, RunEventKind.DONE, run)
    await bus.publish(run_id, RunEventKind.ERROR, RunError(message="после done"))
    await asyncio.wait_for(listener, 1)
    assert received == [1, 2]
    for _ in range(3):
        await bus.publish(uuid4(), RunEventKind.ERROR, RunError(message="x"))
    assert not bus.has_log(run_id)  # старые журналы вытесняются


async def test_project_service_rules(service_container: Container) -> None:
    with pytest.raises(InvalidInputError):
        await service_container.projects.create(title="x" * 201, description=None)
    with pytest.raises(InvalidInputError):
        await service_container.projects.create(title="Ок", description="x" * 2001)
    view = await service_container.projects.create(title="Ок", description="  ")
    assert view.project.description is None


async def test_questions_service_conflicts(service_container: Container) -> None:
    open_questions = await service_container.questions.list(
        DEMO_PROJECT_ID, status=QuestionStatus.OPEN
    )
    question = open_questions[0]
    await service_container.questions.ignore(question.id)
    with pytest.raises(ConflictError):
        await service_container.questions.ignore(question.id)
    with pytest.raises(InvalidInputError):
        await service_container.questions.answer(question.id, text="x" * 20_001)


async def test_parsers() -> None:
    parser = LocalDocumentParser()
    assert await parser.parse(file_name="a.TXT", data="Текст".encode()) == "Текст"
    csv_text = await parser.parse(
        file_name="roles.csv",
        data='Роль;Описание\n"Клиент";"Подаёт заявку; прикладывает документы"\n'.encode(),
    )
    assert 'Строка 1: ["Роль", "Описание"]' in csv_text
    assert 'Строка 2: ["Клиент", "Подаёт заявку; прикладывает документы"]' in csv_text
    quoted_csv = await parser.parse(
        file_name="quoted.csv", data='name,details\n"Роль","Строка 1\nСтрока 2, да"\n'.encode()
    )
    assert 'Строка 2: ["Роль", "Строка 1\\nСтрока 2, да"]' in quoted_csv
    bom_csv = await parser.parse(file_name="bom.csv", data="\ufeffРоль,Клиент".encode())
    assert '["Роль", "Клиент"]' in bom_csv
    cp1251_csv = await parser.parse(file_name="roles.csv", data="Роль;Клиент".encode("cp1251"))
    assert '["Роль", "Клиент"]' in cp1251_csv
    with pytest.raises(DocumentParseError, match="В CSV нет данных"):
        await parser.parse(file_name="blank.csv", data=b" \n\n  \n")
    limited_parser = LocalDocumentParser(max_text_chars=150)
    with pytest.raises(DocumentParseError, match="CSV после разбора превышает лимит 150 символов"):
        await limited_parser.parse(file_name="large.csv", data=b"a,b\n" + b"x,y\n" * 10)
    with pytest.raises(DocumentParseError, match="кавычки и разделители"):
        await parser.parse(file_name="broken.csv", data=b'role,description\n"unfinished')
    with pytest.raises(DocumentParseError, match="бинарные данные"):
        await parser.parse(file_name="binary.csv", data=b"role\x00name")
    with pytest.raises(UnsupportedFormatError):
        await parser.parse(file_name="a.doc", data=b"x")
    with pytest.raises(UnsupportedFormatError):
        await parser.parse(file_name="noext", data=b"x")
    with pytest.raises(DocumentParseError, match="нет текста"):
        await parser.parse(file_name="a.md", data=b"   ")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("other.xml", "<x/>")
    with pytest.raises(DocumentParseError, match="повреждён"):
        await parser.parse(file_name="a.docx", data=buffer.getvalue())
    pdf = _make_pdf(["Submit an application", "The manager approves the application"])
    text = await parser.parse(file_name="process.pdf", data=pdf)
    assert "[Страница 1]\nSubmit an application" in text
    assert "[Страница 2]\nThe manager approves the application" in text
    with pytest.raises(DocumentParseError, match="не найден текстовый слой"):
        await parser.parse(file_name="scan.pdf", data=_make_pdf([""]))
    with pytest.raises(DocumentParseError, match="Не удалось прочитать PDF"):
        await parser.parse(file_name="broken.pdf", data=b"not a PDF")
    assert decode_text(b"\xef\xbb\xbfutf8") == "utf8"


def _make_pdf(pages: list[str]) -> bytes:
    """Минимальный PDF с текстовым слоем для тестов без генераторных зависимостей."""
    font_id = 3 + 2 * len(pages)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{' '.join(f'{3 + 2 * i} 0 R' for i in range(len(pages)))}] "
        f"/Count {len(pages)} >>".encode(),
    ]
    for index, page_text in enumerate(pages):
        page_id = 3 + index * 2
        content_id = page_id + 1
        escaped = page_text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode()
        objects.extend(
            [
                (
                    f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>"
                ).encode(),
                f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
            ]
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for object_id, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{object_id} 0 obj\n".encode() + body + b"\nendobj\n")
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010} 00000 n \n".encode())
    pdf.extend(
        (
            f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n"
        ).encode()
    )
    return bytes(pdf)


async def test_stt_and_storage_and_tools() -> None:
    stt = MockSpeechToText(delay_sec=0)
    short = await stt.transcribe(b"x", mime="audio/webm")
    assert short.duration_sec == 1.0
    assert short.language == "ru-RU"
    storage = InMemoryFileStorage()
    key = await storage.save(project_id=uuid4(), file_name="без расширения", data=b"1")
    assert key.endswith(".bin")
    assert await storage.load(key) == b"1"
    await storage.delete(key)
    tools = MockBpmnTools()
    no_layout = (
        '<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL" targetNamespace="x">'
        '<process id="p"/></definitions>'
    )
    with pytest.raises(ValueError, match="координат"):
        await tools.layout(no_layout)


async def test_spawner_logs_failures() -> None:
    spawner = AsyncioTaskSpawner()

    async def fail() -> None:
        raise RuntimeError("x")

    spawner.spawn(fail(), name="fail")
    await spawner.wait_idle()
    await spawner.shutdown()


def test_seed_is_deterministic() -> None:
    first, second = build_seed(), build_seed()
    assert [p.id for p in first.projects] == [p.id for p in second.projects]
    assert [q.status for q in first.questions] == [q.status for q in second.questions]
    assert len(first.projects) == 5
    kinds = {s.kind for s in first.sources}
    assert kinds == set(SourceKind)
    assert {s.status for s in first.sources} == {"ready"}
    with_versions = {v.project_id for v in first.versions}
    assert len(with_versions) == 5
    assert len(first.retired_project_ids) == 39
    assert not with_versions.intersection(first.retired_project_ids)


async def test_shutdown_then_resume_keeps_run_id_and_creates_one_version(service_container):
    entered = asyncio.Event()

    async def stop_at_reading(_stage):
        entered.set()
        await asyncio.Event().wait()

    service_container.runs._pace = stop_at_reading
    project_id = await _new_project(service_container)
    run = await service_container.runs.start(project_id, mode=RunMode.BUILD, created_by=None)
    await entered.wait()
    await service_container.spawner.shutdown()
    assert (await service_container.runs.get(run.id)).status is RunStatus.QUEUED

    async def no_wait(_stage):
        return None

    service_container.runs._pace = no_wait
    service_container.runs._events = InMemoryRunEventBus()
    service_container.runs.resume(run.id)
    await service_container.spawner.wait_idle()
    saved = await service_container.runs.get(run.id)
    assert saved.status is RunStatus.SUCCEEDED
    versions = await service_container.runs._repos.versions.list_by_project(project_id)
    assert len(versions) == 1
    assert versions[0].run_id == run.id


async def test_recovery_refuses_changed_sources(service_container):
    entered = asyncio.Event()

    async def stop(_stage):
        entered.set()
        await asyncio.Event().wait()

    project_id = await _new_project(service_container)
    service_container.runs._pace = stop
    run = await service_container.runs.start(project_id, mode=RunMode.BUILD, created_by=None)
    await entered.wait()
    await service_container.spawner.shutdown()
    await service_container.sources.create_text(
        project_id, content="Новый регламент", title=None, kind=SourceKind.TEXT, duration_sec=None
    )

    async def no_wait(_stage):
        return None

    service_container.runs._pace = no_wait
    service_container.runs._events = InMemoryRunEventBus()
    service_container.runs.resume(run.id)
    await service_container.spawner.wait_idle()
    saved = await service_container.runs.get(run.id)
    assert saved.status is RunStatus.FAILED
    assert "Источники изменились" in saved.error
    assert await service_container.runs._repos.versions.list_by_project(project_id) == []
