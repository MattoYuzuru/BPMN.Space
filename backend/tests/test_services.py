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
    MockDocumentParser,
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
        await service_container.runs.start(p, mode=RunMode.ANALYZE) for p in projects
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


async def test_cancelled_run_is_failed(service_container: Container) -> None:
    async def forever(_: RunStage) -> None:
        await asyncio.sleep(3600)

    service_container.runs._pace = forever
    run = await service_container.runs.start(DEMO_PROJECT_ID, mode=RunMode.BUILD)
    await asyncio.sleep(0.01)
    await service_container.spawner.shutdown()
    final = await service_container.runs.get(run.id)
    assert final.status is RunStatus.FAILED
    assert final.error == "Прогон прерван остановкой сервера"


async def test_unexpected_error_marks_run_failed(service_container: Container) -> None:
    async def boom(_: RunStage) -> None:
        raise RuntimeError("сбой")

    service_container.runs._pace = boom
    run = await service_container.runs.start(DEMO_PROJECT_ID, mode=RunMode.ANALYZE)
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
    parser = MockDocumentParser()
    assert await parser.parse(file_name="a.TXT", data="Текст".encode()) == "Текст"
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
    assert decode_text(b"\xef\xbb\xbfutf8") == "utf8"


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
    assert len(first.projects) == 41
    kinds = {s.kind for s in first.sources}
    assert kinds == set(SourceKind)
    assert {s.status for s in first.sources} == {"ready", "failed"}
    assert any(not s.active for s in first.sources)
    with_versions = {v.project_id for v in first.versions}
    assert len(with_versions) >= 20
