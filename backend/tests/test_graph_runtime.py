"""Настоящий Node HTTP, сохранение графа и manual-priority без live LLM."""

import asyncio
import json
import select
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4
from xml.etree.ElementTree import tostring

import pytest
from defusedxml.ElementTree import fromstring
from lxml import etree

from app.domain.analysis import AnalysisResult, ContextSource, RunContext
from app.domain.bpmn.compiler import compile_graph
from app.domain.bpmn.importer import import_graph, preserve_geometry
from app.domain.bpmn.ir import GraphIR
from app.domain.bpmn.xsd import XSD_ENTRY
from app.domain.models import (
    Project,
    Question,
    QuestionKind,
    QuestionStatus,
    RunMode,
    RunStatus,
    RunSummary,
    Severity,
    Source,
    SourceKind,
    SourceStatus,
)
from app.infra.bpmn_tools import BpmnToolsError, HttpBpmnTools
from app.infra.events import InMemoryRunEventBus
from app.infra.repositories.memory import InMemoryStore
from app.infra.tasks import AsyncioTaskSpawner
from app.llm.base import PipelineError
from app.llm.openai_compatible import OpenAICompatiblePipeline
from app.services.common import Runtime
from app.services.runs import RunService
from tests.test_graph_ir import SOURCE_ID, TEXT, graph_case

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def node_url():
    code = (
        "import {createToolsServer} from './server.mjs';const server=createToolsServer();"
        "server.listen(0,'127.0.0.1',()=>process.stdout.write(String(server.address().port)+'\\n'));"
    )
    process = subprocess.Popen(  # noqa: S603 — фиксированный локальный процесс проверки
        [shutil.which("node") or "node", "--input-type=module", "-e", code],
        cwd=ROOT / "infra" / "bpmn-tools",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        assert process.stdout is not None
        assert select.select([process.stdout], [], [], 10)[0], "Node не запустился"
        port = int(process.stdout.readline().decode().strip())
        yield f"http://127.0.0.1:{port}"
    finally:
        process.terminate()
        process.wait(timeout=5)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["xor", "and", "nested", "loop", "starts", "parallel_ends"])
async def test_generated_graph_goes_through_real_http_tools(case, node_url):
    tools = HttpBpmnTools(node_url)
    xml = await tools.layout(compile_graph(GraphIR.model_validate(graph_case(case))))
    schema = etree.XMLSchema(etree.parse(str(XSD_ENTRY)))
    assert schema.validate(etree.fromstring(xml.encode())), schema.error_log
    errors = [i for i in await tools.lint(xml) if i.severity.value == "error"]
    assert errors == [], errors
    assert (await tools.layout(xml)) == xml


@pytest.mark.asyncio
async def test_unavailable_service_is_explicit_failure():
    with pytest.raises(BpmnToolsError, match="связаться"):
        await HttpBpmnTools("http://127.0.0.1:1", timeout_sec=0.1).layout("<xml/>")


@pytest.mark.asyncio
async def test_manual_name_and_geometry_survive_and_conflict_is_visible(node_url):
    tools = HttpBpmnTools(node_url)
    original = GraphIR.model_validate(graph_case())
    base_xml = await tools.layout(compile_graph(original))
    manual_xml = base_xml.replace('name="Check"', 'name="Ручная проверка"')
    # Перемещение одной фигуры никак не создаёт/не теряет бизнес-семантику.
    root = fromstring(manual_xml)
    ns = {
        "bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
        "dc": "http://www.omg.org/spec/DD/20100524/DC",
    }
    bounds = root.find('.//bpmndi:BPMNShape[@bpmnElement="Check"]/dc:Bounds', ns)
    assert bounds is not None
    bounds.set("x", "1200")
    bounds.set("y", "320")

    manual_xml = tostring(root, encoding="unicode")
    source = ContextSource(
        id=SOURCE_ID,
        kind=SourceKind.TEXT,
        title="Регламент",
        content=TEXT,
        created_at=datetime.now(UTC),
    )
    context = RunContext(
        project_id=uuid4(),
        project_title="Заявка",
        sources=[source],
        questions=[],
        current_xml=manual_xml,
        current_is_manual=True,
        base_generated_xml=base_xml,
    )
    pipeline = OpenAICompatiblePipeline(
        api_key="test-only", complete=lambda _s, _p: json.dumps(graph_case())
    )
    draft = await pipeline.structure(context, AnalysisResult())
    assert draft.ir is not None
    assert import_graph(draft.xml).nodes[1].id  # Валидный граф, не готовый XML модели.
    assert next(n for n in draft.ir["nodes"] if n["id"] == "Check")["name"] == "Ручная проверка"
    assert draft.conflicts
    assert "Check" not in draft.trace
    laid_out = await tools.layout(draft.xml)
    kept = preserve_geometry(laid_out, manual_xml)
    after = fromstring(kept).find('.//bpmndi:BPMNShape[@bpmnElement="Check"]/dc:Bounds', ns)
    assert after is not None
    assert after.get("x") == "1200"
    assert after.get("y") == "320"
    schema = etree.XMLSchema(etree.parse(str(XSD_ENTRY)))
    assert schema.validate(etree.fromstring(kept.encode())), schema.error_log


@pytest.mark.asyncio
async def test_explicit_replace_can_leave_opaque_manual_and_default_blocks_it():
    source = ContextSource(
        id=SOURCE_ID,
        kind=SourceKind.TEXT,
        title="Регламент",
        content=TEXT,
        created_at=datetime.now(UTC),
    )
    opaque = (
        compile_graph(GraphIR.model_validate(graph_case()))
        .replace('<bpmn:task id="Check"', '<bpmn:userTask id="Check"')
        .replace("</bpmn:task>", "</bpmn:userTask>")
    )
    # Точный unsupported-node case, без повреждения остальных закрывающих тегов.
    opaque = (
        compile_graph(GraphIR.model_validate(graph_case()))
        .replace('<bpmn:task id="Check"', '<bpmn:subProcess id="Check"')
        .replace("</bpmn:task>", "</bpmn:subProcess>", 1)
    )
    pipeline = OpenAICompatiblePipeline(
        api_key="test-only", complete=lambda _s, _p: json.dumps(graph_case())
    )
    context = RunContext(
        project_id=uuid4(),
        project_title="Заявка",
        sources=[source],
        questions=[],
        current_xml=opaque,
        current_is_manual=True,
    )
    with pytest.raises(PipelineError, match="не совместима"):
        await pipeline.structure(context, AnalysisResult())
    context.replace_manual = True
    draft = await pipeline.structure(context, AnalysisResult())
    assert draft.ir
    assert "subProcess" not in draft.xml


@pytest.mark.asyncio
async def test_sources_recorded_ir_xml_version_roundtrip_and_audit(node_url):
    store = InMemoryStore()
    repos = store.repositories()
    now = datetime.now(UTC)
    pid = uuid4()
    await repos.projects.add(
        Project(
            id=pid,
            title="Параллельное согласование",
            description=None,
            created_at=now,
            updated_at=now,
        )
    )
    await repos.sources.add(
        Source(
            id=SOURCE_ID,
            project_id=pid,
            kind=SourceKind.TEXT,
            title="Регламент",
            content=TEXT,
            status=SourceStatus.READY,
            active=True,
            created_at=now,
        )
    )

    def complete(system, prompt):
        return (
            json.dumps({"new_questions": []})
            if "new_questions" in system
            else json.dumps(graph_case("nested"))
        )

    pipeline = OpenAICompatiblePipeline(api_key="test-only", complete=complete)
    spawner = AsyncioTaskSpawner()
    runs = RunService(
        repos,
        pipeline=pipeline,
        bpmn_tools=HttpBpmnTools(node_url),
        events=InMemoryRunEventBus(),
        spawner=spawner,
        runtime=Runtime(),
        max_concurrent=2,
    )
    run = await runs.start(pid, mode=RunMode.BUILD, created_by=None)
    actual = await runs.get(run.id)
    for _ in range(100):
        actual = await runs.get(run.id)
        if actual.status in {RunStatus.SUCCEEDED, RunStatus.FAILED}:
            break
        await asyncio.sleep(0.03)
    assert actual.status is RunStatus.SUCCEEDED, actual.error
    assert actual.ir
    assert actual.ir["graph"]["schema_version"] == 1
    saved = await repos.versions.latest(pid)
    assert saved is not None
    assert "parallelGateway" in saved.xml
    assert "exclusiveGateway" in saved.xml
    assert saved.trace["AccountingTask"].quote == TEXT
    assert len([call for call in store.llm_calls.values() if call.run_id == run.id]) == 2
    await spawner.shutdown()


@pytest.mark.asyncio
async def test_new_task_keeps_fixed_manual_position_and_expands_pool_lane(node_url):
    tools = HttpBpmnTools(node_url)
    before = await tools.layout(compile_graph(GraphIR.model_validate(graph_case())))
    root = fromstring(before)
    ns = {
        "bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
        "dc": "http://www.omg.org/spec/DD/20100524/DC",
    }
    bounds = root.find('.//bpmndi:BPMNShape[@bpmnElement="Check"]/dc:Bounds', ns)
    assert bounds is not None
    bounds.set("x", "2000")
    bounds.set("y", "700")

    manual = tostring(root, encoding="unicode")
    data = graph_case()
    data["nodes"].append(
        {
            "id": "Archive",
            "type": "task",
            "name": "Архивировать заявку",
            "lane": "Operator",
            "source": {"source_id": str(SOURCE_ID), "quote": TEXT},
        }
    )
    next(f for f in data["flows"] if f["id"] == "F5")["target_id"] = "Archive"
    data["flows"].append({"id": "FArchive", "source_id": "Archive", "target_id": "End"})
    laid_out = await tools.layout(compile_graph(GraphIR.model_validate(data)))
    kept = fromstring(preserve_geometry(laid_out, manual))
    actual = kept.find('.//bpmndi:BPMNShape[@bpmnElement="Check"]/dc:Bounds', ns)
    assert actual is not None
    assert actual.get("x") == "2000"
    assert actual.get("y") == "700"
    for element_id in ["Operator", "Participant_1"]:
        box = kept.find(f'.//bpmndi:BPMNShape[@bpmnElement="{element_id}"]/dc:Bounds', ns)
        assert box is not None
        assert float(box.get("x", "0")) + float(box.get("width", "0")) >= 2000 + float(
            actual.get("width", "0")
        )
        assert float(box.get("y", "0")) + float(box.get("height", "0")) >= 700 + float(
            actual.get("height", "0")
        )
    schema = etree.XMLSchema(etree.parse(str(XSD_ENTRY)))
    assert schema.validate(etree.fromstring(tostring(kept))), schema.error_log


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["new_source", "inactive", "title", "question"])
async def test_changed_knowledge_does_not_publish_old_graph(node_url, change):

    store = InMemoryStore()
    repos = store.repositories()
    now = datetime.now(UTC)
    pid = uuid4()
    await repos.projects.add(
        Project(id=pid, title="Согласование", description=None, created_at=now, updated_at=now)
    )
    await repos.sources.add(
        Source(
            id=SOURCE_ID,
            project_id=pid,
            kind=SourceKind.TEXT,
            title="Регламент",
            content=TEXT,
            status=SourceStatus.READY,
            active=True,
            created_at=now,
        )
    )
    qid = uuid4()
    await repos.questions.add(
        Question(
            id=qid,
            project_id=pid,
            code="Q-1",
            kind=QuestionKind.MISSING_ACTOR,
            severity=Severity.MAJOR,
            status=QuestionStatus.OPEN,
            text="Кто готовит акт?",
            assumption="Оператор",
            created_at=now,
            updated_at=now,
        )
    )
    ready = asyncio.Event()
    release = asyncio.Event()

    class PausingPipeline(OpenAICompatiblePipeline):
        async def structure(self, context, analysis):
            result = await super().structure(context, analysis)
            ready.set()
            await release.wait()
            return result

    def complete(system, _prompt):
        return (
            json.dumps({"new_questions": []})
            if "new_questions" in system
            else json.dumps(graph_case())
        )

    spawner = AsyncioTaskSpawner()
    runs = RunService(
        repos,
        pipeline=PausingPipeline(api_key="test-only", complete=complete),
        bpmn_tools=HttpBpmnTools(node_url),
        events=InMemoryRunEventBus(),
        spawner=spawner,
        runtime=Runtime(),
        max_concurrent=2,
    )
    run = await runs.start(pid, mode=RunMode.BUILD, created_by=None)
    await asyncio.wait_for(ready.wait(), 5)
    if change == "new_source":
        await repos.sources.add(
            Source(
                id=uuid4(),
                project_id=pid,
                kind=SourceKind.TEXT,
                title="Дополнение",
                content="Другой порядок согласования.",
                status=SourceStatus.READY,
                active=True,
                created_at=now,
            )
        )
    elif change == "question":
        question = await repos.questions.get(qid)
        assert question is not None
        question.assumption = "Инженер"
        await repos.questions.update(question)
    else:
        await repos.sources.patch(
            SOURCE_ID, {"active": False} if change == "inactive" else {"title": "Новый заголовок"}
        )
    release.set()
    await spawner.wait_idle()
    actual = await runs.get(run.id)
    assert actual.status is RunStatus.FAILED
    assert actual.error
    assert "измен" in actual.error
    assert await repos.versions.latest(pid) is None


@pytest.mark.asyncio
async def test_supported_task_subtypes_roundtrip():
    for kind in ["task", "userTask", "manualTask", "sendTask", "receiveTask", "serviceTask"]:
        data = graph_case()
        next(n for n in data["nodes"] if n["id"] == "Check")["task_kind"] = kind
        xml = compile_graph(GraphIR.model_validate(data))
        assert next(n for n in import_graph(xml).nodes if n.id == "Check").task_kind == kind


@pytest.mark.asyncio
async def test_manual_conflict_question_preserves_resolved_summary_and_bindings(node_url):

    store = InMemoryStore()
    repos = store.repositories()
    now = datetime.now(UTC)
    pid = uuid4()
    await repos.projects.add(
        Project(id=pid, title="Согласование", description=None, created_at=now, updated_at=now)
    )
    await repos.sources.add(
        Source(
            id=SOURCE_ID,
            project_id=pid,
            kind=SourceKind.TEXT,
            title="Регламент",
            content=TEXT,
            status=SourceStatus.READY,
            active=True,
            created_at=now,
        )
    )
    source = ContextSource(
        id=SOURCE_ID, kind=SourceKind.TEXT, title="Регламент", content=TEXT, created_at=now
    )
    base_xml = await HttpBpmnTools(node_url).layout(
        compile_graph(GraphIR.model_validate(graph_case()))
    )
    manual_xml = base_xml.replace('name="Check"', 'name="Ручная проверка"')
    context = RunContext(
        project_id=pid,
        project_title="Согласование",
        sources=[source],
        evidence_sources=[source],
        questions=[],
        current_xml=manual_xml,
        current_is_manual=True,
        base_generated_xml=base_xml,
    )
    pipeline = OpenAICompatiblePipeline(
        api_key="test-only", complete=lambda _s, _p: json.dumps(graph_case())
    )
    draft = await pipeline.structure(context, AnalysisResult())
    assert draft.conflicts
    spawner = AsyncioTaskSpawner()
    runs = RunService(
        repos,
        pipeline=pipeline,
        bpmn_tools=HttpBpmnTools(node_url),
        events=InMemoryRunEventBus(),
        spawner=spawner,
        runtime=Runtime(),
        max_concurrent=2,
    )
    run = await runs.start(pid, mode=RunMode.BUILD, created_by=None)
    await spawner.wait_idle()
    run.summary = RunSummary(resolved=2)
    await runs._graph_questions(repos, run, draft)
    assert run.summary.resolved == 2
    questions = await repos.questions.list_by_project(pid)
    assert len(questions) == 1
    assert questions[0].element_ids == ["Check"]
    assert "Ручная проверка" in questions[0].text
    assert "direction" not in questions[0].text
    assert "event_kind" not in questions[0].text
    await spawner.shutdown()
