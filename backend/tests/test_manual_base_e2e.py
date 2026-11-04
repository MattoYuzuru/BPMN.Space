"""Сквозная защита ручных правок: база сравнения берётся из прошлой generated-версии."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.domain.bpmn.compiler import compile_graph
from app.domain.bpmn.ir import GraphIR
from app.domain.models import (
    Project,
    RunMode,
    RunStatus,
    Source,
    SourceKind,
    SourceStatus,
    VersionOrigin,
)
from app.infra.bpmn_tools import HttpBpmnTools
from app.infra.events import InMemoryRunEventBus
from app.infra.repositories.memory import InMemoryStore
from app.infra.tasks import AsyncioTaskSpawner
from app.llm.openai_compatible import OpenAICompatiblePipeline
from app.services.common import Runtime
from app.services.runs import RunService
from app.services.versions import add_version
from tests.test_graph_ir import SOURCE_ID, TEXT, graph_case
from tests.test_graph_runtime import node_url, recorded_reply  # noqa: F401 — фикстура Node


@pytest.mark.asyncio
async def test_rebuild_protects_only_manual_edit_and_remembers_removal(node_url):  # noqa: F811
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
    tools = HttpBpmnTools(node_url)
    pipeline = OpenAICompatiblePipeline(
        api_key="test-only", complete=lambda _s, prompt: recorded_reply(prompt)
    )
    spawner = AsyncioTaskSpawner()
    runtime = Runtime()
    runs = RunService(
        repos,
        pipeline=pipeline,
        bpmn_tools=tools,
        events=InMemoryRunEventBus(),
        spawner=spawner,
        runtime=runtime,
        max_concurrent=2,
    )
    first = await runs.start(pid, mode=RunMode.BUILD, created_by=None)
    await spawner.wait_idle()
    assert (await runs.get(first.id)).status is RunStatus.SUCCEEDED

    # Человек переименовал Check и удалил Accept (Yes теперь ведёт сразу в Merge).
    manual = graph_case()
    for item in manual["nodes"]:
        if item["id"] == "Check":
            item["name"] = "Ручная проверка"
    manual["nodes"] = [n for n in manual["nodes"] if n["id"] != "Accept"]
    manual["flows"] = [f for f in manual["flows"] if f["id"] != "F3"]
    for item in manual["flows"]:
        if item["id"] == "Yes":
            item["target_id"] = "Merge"
    manual_xml = await tools.layout(compile_graph(GraphIR.model_validate(manual)))
    await add_version(
        repos,
        runtime,
        project_id=pid,
        xml=manual_xml,
        origin=VersionOrigin.MANUAL,
        lint=[],
        trace={},
    )

    second = await runs.start(pid, mode=RunMode.BUILD, created_by=None)
    await spawner.wait_idle()
    done = await runs.get(second.id)
    assert done.status is RunStatus.SUCCEEDED, done.error
    assert done.ir is not None
    overrides = done.ir["manual_overrides"]
    assert overrides["protected"]["nodes"] == ["Check"]
    assert overrides["removed"]["nodes"] == ["Accept"]
    assert overrides["protected"]["flows"] == ["Yes"]
    await spawner.shutdown()


@pytest.mark.asyncio
async def test_start_slot_is_per_project_and_cleans_up():
    store = InMemoryStore()
    runs = RunService(
        store.repositories(),
        pipeline=None,  # type: ignore[arg-type]
        bpmn_tools=None,  # type: ignore[arg-type]
        events=InMemoryRunEventBus(),
        spawner=AsyncioTaskSpawner(),
        runtime=Runtime(),
        max_concurrent=1,
    )
    first, second = uuid4(), uuid4()
    order: list[str] = []
    gate = asyncio.Event()

    async def hold(project):
        async with runs._start_slot(project):
            order.append(f"in-{project}")
            await gate.wait()

    t1 = asyncio.create_task(hold(first))
    await asyncio.sleep(0)
    t2 = asyncio.create_task(hold(second))
    await asyncio.sleep(0.01)
    assert len(order) == 2  # разные проекты не ждут друг друга
    t3 = asyncio.create_task(hold(first))
    await asyncio.sleep(0.01)
    assert len(order) == 2  # тот же проект — по очереди
    gate.set()
    await asyncio.gather(t1, t2, t3)
    assert len(order) == 3
    assert runs._start_locks == {}
