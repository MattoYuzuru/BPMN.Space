# ruff: noqa: F811 — фикстура `stack` импортируется из test_auth_http
"""Онбординг по HTTP с аккаунтами на PostgreSQL: ручки `/me/onboarding*`, точки учёта, права.

Нужен TEST_DATABASE_URL (см. `make test-postgres`), иначе тесты пропускаются.
"""

import asyncio
import os
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.domain.onboarding import ChecklistItem, ItemSource, TourStatus, TourStepKey
from app.fixtures.samples import TOUR_SAMPLE_ID, tour_text_suggestion
from app.infra.seed import DEMO_PROJECT_ID
from tests.test_auth_http import (  # noqa: F401
    MIGRATIONS_DIR,
    Account,
    Stack,
    _finished_project,
    stack,
)

pytestmark = pytest.mark.asyncio

NOBODY = "00000000-0000-4000-8000-000000000000"
SERVER_ITEMS = [
    "project_created",
    "text_source_added",
    "document_uploaded",
    "voice_added",
    "diagram_built",
    "question_answered",
    "assumption_accepted",
    "diagram_rebuilt",
    "diagram_edited",
    "project_shared",
]


async def _state(account: Account) -> dict[str, Any]:
    response = await account.get("/me/onboarding")
    assert response.status_code == 200, response.text
    return response.json()


async def _done(account: Account) -> list[str]:
    return [item["key"] for item in (await _state(account))["checklist"]["items"]]


async def _wait_run(account: Account, run_id: str) -> dict[str, Any]:
    run: dict[str, Any] = {}
    for _ in range(200):
        run = (await account.get(f"/runs/{run_id}")).json()
        if run["status"] not in {"queued", "running"}:
            return run
        await asyncio.sleep(0.05)
    raise AssertionError(run)


async def _build(account: Account, project_id: str) -> dict[str, Any]:
    started = await account.post(f"/projects/{project_id}/runs", json={"mode": "build"})
    assert started.status_code == 202, started.text
    return await _wait_run(account, started.json()["id"])


# ---------- сессия и права ----------


async def test_guest_gets_disabled_state_and_401_elsewhere(stack: Stack) -> None:
    guest = await stack.guest()
    response = await guest.get("/me/onboarding")
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert response.json()["tour"] is None
    for method, path, body in (
        ("PATCH", "/me/onboarding/tour", {"status": "dismissed"}),
        ("POST", "/me/onboarding/tour/restart", None),
        ("PATCH", "/me/onboarding/checklist", {"hidden": True}),
        ("POST", "/me/onboarding/events", {"item": "simulation_run"}),
        ("GET", "/me/onboarding/items/project_shared/target", None),
    ):
        answer = await guest.request(method, path, json=body)
        assert answer.status_code == 401, (path, answer.text)


async def test_samples_are_public_like_examples(stack: Stack) -> None:
    guest = await stack.guest()
    response = await guest.get("/samples")
    assert response.status_code == 200
    assert len(response.json()) == 4


async def test_state_is_per_user_and_created_lazily(stack: Stack) -> None:
    first = await stack.user("onb-first@example.com")
    second = await stack.user("onb-second@example.com")
    state = await _state(first)
    assert state["enabled"] is True
    assert state["tour"]["status"] == "pending"
    assert state["tour"]["step"] is None
    assert state["tour"]["project_id"] is None
    assert state["checklist"] == {"hidden": False, "items": []}
    assert state["tour_text_suggestion"] == tour_text_suggestion()
    await first.post("/projects", json={"title": "Один"})
    assert await _done(first) == ["project_created"]
    assert await _done(second) == []


async def test_tour_endpoints_flow_and_conflicts(stack: Stack) -> None:
    user = await stack.user("onb-tour@example.com")
    own = (await user.post("/projects", json={"title": "Учебный"})).json()["id"]

    started = await user.patch("/me/onboarding/tour", json={"status": "active"})
    assert started.status_code == 200
    assert started.json()["tour"]["step"] == "project.create"
    moved = await user.patch(
        "/me/onboarding/tour", json={"step": "sources.sample", "project_id": own}
    )
    assert moved.json()["tour"]["step"] == "sources.sample"
    assert moved.json()["tour"]["project_id"] == own

    assert (await user.patch("/me/onboarding/tour", json={"step": "нет такого"})).status_code == 422
    assert (await user.patch("/me/onboarding/tour", json={"status": "bogus"})).status_code == 422

    done = await user.patch("/me/onboarding/tour", json={"status": "completed"})
    assert done.json()["tour"]["status"] == "completed"
    assert done.json()["tour"]["step"] is None
    conflict = await user.patch("/me/onboarding/tour", json={"status": "active"})
    assert conflict.status_code == 409
    assert (await user.patch("/me/onboarding/tour", json={"step": "run.start"})).status_code == 409

    restarted = await user.post("/me/onboarding/tour/restart")
    assert restarted.status_code == 200
    assert restarted.json()["tour"] == {
        **restarted.json()["tour"],
        "status": "active",
        "step": "project.create",
        "project_id": None,
    }


async def test_tour_project_must_be_own_project(stack: Stack) -> None:
    owner = await stack.user("onb-owner@example.com")
    other = await stack.user("onb-other@example.com")
    foreign = (await owner.post("/projects", json={"title": "Чужой"})).json()["id"]
    await other.patch("/me/onboarding/tour", json={"status": "active"})
    for project_id in (foreign, NOBODY, str(DEMO_PROJECT_ID)):  # чужой, несуществующий, демо
        response = await other.patch("/me/onboarding/tour", json={"project_id": project_id})
        assert response.status_code == 404, response.text


async def test_deleting_the_tour_project_clears_the_reference(stack: Stack) -> None:
    user = await stack.user("onb-delete@example.com")
    own = (await user.post("/projects", json={"title": "Учебный"})).json()["id"]
    await user.patch("/me/onboarding/tour", json={"status": "active", "project_id": own})
    assert (await user.delete(f"/projects/{own}")).status_code == 204
    assert (await _state(user))["tour"]["project_id"] is None


async def test_checklist_visibility(stack: Stack) -> None:
    user = await stack.user("onb-hide@example.com")
    hidden = await user.patch("/me/onboarding/checklist", json={"hidden": True})
    assert hidden.json()["checklist"]["hidden"] is True
    assert (await _state(user))["checklist"]["hidden"] is True
    assert (await user.patch("/me/onboarding/checklist", json={})).status_code == 422


async def test_events_accept_only_client_items_and_are_idempotent(stack: Stack) -> None:
    user = await stack.user("onb-events@example.com")
    for _ in range(2):
        assert (
            await user.post("/me/onboarding/events", json={"item": "simulation_run"})
        ).status_code == 204
    assert (
        await user.post("/me/onboarding/events", json={"item": "diagram_exported"})
    ).status_code == 204
    items = (await _state(user))["checklist"]["items"]
    assert [(i["key"], i["source"]) for i in items] == [
        ("simulation_run", "client"),
        ("diagram_exported", "client"),
    ]
    for key in SERVER_ITEMS:
        response = await user.post("/me/onboarding/events", json={"item": key})
        assert response.status_code == 422, key
    assert (await user.post("/me/onboarding/events", json={"item": "nope"})).status_code == 422
    assert len((await _state(user))["checklist"]["items"]) == 2


async def test_unsafe_requests_need_csrf(stack: Stack) -> None:
    user = await stack.user("onb-csrf@example.com")
    response = await user.http.patch("/api/v1/me/onboarding/tour", json={"status": "dismissed"})
    assert response.status_code == 403


# ---------- точки учёта ----------


async def test_every_server_action_marks_its_item_exactly_once(stack: Stack) -> None:
    owner = await stack.user("onb-owner-flow@example.com")
    editor = await stack.user("onb-editor-flow@example.com")

    created = await owner.post("/projects", json={"title": "Свой"})
    pid = created.json()["id"]
    assert await _done(owner) == ["project_created"]
    await owner.post("/projects", json={"title": "Ещё один"})
    assert await _done(owner) == ["project_created"]  # повтор ничего не меняет

    first_stamp = (await _state(owner))["checklist"]["items"][0]["completed_at"]
    await owner.post("/projects/from-example", json={"example_id": "tp861"})
    assert (await _state(owner))["checklist"]["items"][0]["completed_at"] == first_stamp

    assert (
        await owner.post(f"/projects/{pid}/sources/text", json={"content": "Принять заявку."})
    ).status_code == 201
    assert (
        await owner.post(
            f"/projects/{pid}/sources/text",
            json={"content": "Надиктовал процесс.", "kind": "voice"},
        )
    ).status_code == 201
    uploaded = await owner.post(
        f"/projects/{pid}/sources/file",
        files={"file": ("процесс.md", "1. Принять заявку. Ответственный: оператор.".encode())},
    )
    assert uploaded.status_code == 201
    assert await _done(owner) == [
        "project_created",
        "text_source_added",
        "voice_added",
        "document_uploaded",
    ]

    link = await owner.post(f"/projects/{pid}/share-links", json={"role": "editor"})
    assert link.status_code == 201
    assert "project_shared" in await _done(owner)
    token = link.json()["url_path"].removeprefix("/share/")
    assert (await editor.post(f"/shares/{token}/accept")).status_code == 200

    run = await _build(editor, pid)  # собирает редактор по ссылке, а не владелец
    assert run["status"] == "succeeded"
    assert "diagram_built" in await _done(editor)
    assert "diagram_built" not in await _done(owner)

    questions = (await editor.get(f"/projects/{pid}/questions")).json()
    first, second = questions[0]["id"], questions[1]["id"]
    assert (
        await editor.post(f"/questions/{first}/answer", json={"text": "Оператор."})
    ).status_code == 200
    assert (await editor.post(f"/questions/{second}/ignore")).status_code == 200
    assert {"question_answered", "assumption_accepted"} <= set(await _done(editor))
    assert "question_answered" not in await _done(owner)

    rebuilt = await _build(editor, pid)
    assert rebuilt["status"] == "succeeded"
    assert "diagram_rebuilt" in await _done(editor)

    xml = (await editor.get(f"/versions/{rebuilt['version_id']}")).json()["xml"]
    saved = await editor.put(f"/projects/{pid}/diagram", json={"xml": xml})
    assert saved.status_code == 201, saved.text
    assert "diagram_edited" in await _done(editor)

    done = await _done(editor)
    assert len(done) == len(set(done))  # каждый пункт — ровно одна запись
    assert {i["source"] for i in (await _state(editor))["checklist"]["items"]} == {"server"}


async def test_sample_sources_mark_document_or_voice(stack: Stack) -> None:
    user = await stack.user("onb-sample@example.com")
    pid = (await user.post("/projects", json={"title": "Тур"})).json()["id"]
    voice = await user.post(
        f"/projects/{pid}/sources/sample", json={"sample_id": "voice-request-approval"}
    )
    assert voice.status_code == 201, voice.text
    assert voice.json()["kind"] == "voice"
    assert await _done(user) == ["project_created", "voice_added"]
    document = await user.post(
        f"/projects/{pid}/sources/sample", json={"sample_id": TOUR_SAMPLE_ID}
    )
    assert document.status_code == 201, document.text
    assert document.json()["kind"] == "file"
    assert await _done(user) == ["project_created", "voice_added", "document_uploaded"]
    sources: list[dict[str, Any]] = []
    for _ in range(100):
        sources = (await user.get(f"/projects/{pid}")).json()["sources"]
        if all(s["status"] == "ready" for s in sources):
            break
        await asyncio.sleep(0.05)
    assert all(s["status"] == "ready" for s in sources)
    docx = next(s for s in sources if s["kind"] == "file")
    assert "Записка со встречи" in docx["content"]


async def test_sample_source_respects_project_access(stack: Stack) -> None:
    owner = await stack.user("onb-sample-owner@example.com")
    stranger = await stack.user("onb-sample-stranger@example.com")
    pid = (await owner.post("/projects", json={"title": "Закрытый"})).json()["id"]
    body = {"sample_id": TOUR_SAMPLE_ID}
    assert (await stranger.post(f"/projects/{pid}/sources/sample", json=body)).status_code == 404
    guest = await stack.guest()
    assert (await guest.post(f"/projects/{pid}/sources/sample", json=body)).status_code == 401
    assert "document_uploaded" not in await _done(stranger)
    viewer = await stranger.post(f"/projects/{DEMO_PROJECT_ID}/sources/sample", json=body)
    assert viewer.status_code == 403  # демо — только чтение


async def test_recording_failure_never_breaks_the_main_action(stack: Stack) -> None:
    user = await stack.user("onb-broken@example.com")
    store = stack.app.state.container.repos.onboarding

    async def boom(*_: object, **__: object) -> bool:
        raise RuntimeError("БД онбординга недоступна")

    store.add_item = boom
    try:
        created = await user.post("/projects", json={"title": "Работает"})
        assert created.status_code == 201
        pid = created.json()["id"]
        text = await user.post(f"/projects/{pid}/sources/text", json={"content": "Принять заявку."})
        assert text.status_code == 201
        assert (await _build(user, pid))["status"] == "succeeded"
        question = (await user.get(f"/projects/{pid}/questions")).json()[0]["id"]
        assert (await user.post(f"/questions/{question}/ignore")).status_code == 200
        link = await user.post(f"/projects/{pid}/share-links", json={"role": "viewer"})
        assert link.status_code == 201
    finally:
        del store.add_item
    assert await _done(user) == []


# ---------- куда вести ----------


async def test_target_endpoint_follows_projects(stack: Stack) -> None:
    user = await stack.user("onb-target@example.com")
    nothing = await user.get("/me/onboarding/items/diagram_edited/target")
    assert nothing.status_code == 200
    assert nothing.json() == {
        "route": "projects",
        "project_id": None,
        "question_id": None,
        "hint": "need_project",
    }  # демо-проект только для чтения не считается
    assert (await user.get("/me/onboarding/items/bogus/target")).status_code == 422

    ids = await _finished_project(user)
    target = (await user.get("/me/onboarding/items/diagram_edited/target")).json()
    assert target["route"] == "workspace"
    assert target["project_id"] == ids["project"]
    assert target["hint"] == "do_item"
    asked = (await user.get("/me/onboarding/items/question_answered/target")).json()
    assert asked["project_id"] == ids["project"]
    assert asked["question_id"] is not None
    shared = (await user.get("/me/onboarding/items/project_shared/target")).json()
    assert shared["project_id"] == ids["project"]
    created = (await user.get("/me/onboarding/items/project_created/target")).json()
    assert created["route"] == "projects"
    assert created["hint"] == "do_item"


async def test_target_counts_editable_shared_projects_but_not_viewer_links(stack: Stack) -> None:
    owner = await stack.user("onb-target-owner@example.com")
    editor = await stack.user("onb-target-editor@example.com")
    viewer = await stack.user("onb-target-viewer@example.com")
    pid = (await owner.post("/projects", json={"title": "Общий"})).json()["id"]
    invite = await owner.post(f"/projects/{pid}/share-links", json={"role": "editor"})
    await editor.post(f"/shares/{invite.json()['url_path'].removeprefix('/share/')}/accept")
    read_only = await owner.post(f"/projects/{pid}/share-links", json={"role": "viewer"})
    token = read_only.json()["url_path"].removeprefix("/share/")
    await viewer.get(f"/shares/{token}")

    for_editor = (await editor.get("/me/onboarding/items/text_source_added/target")).json()
    assert for_editor["project_id"] == pid  # по приглашению редактора проект доступен на правку
    own_only = (await editor.get("/me/onboarding/items/project_shared/target")).json()
    assert own_only["route"] == "projects"  # делиться можно только своим
    for_viewer = (await viewer.get("/me/onboarding/items/text_source_added/target")).json()
    assert for_viewer["route"] == "projects"
    assert for_viewer["hint"] == "need_project"


# ---------- SQL-репозиторий и миграция 0008 ----------


async def test_sql_repository_semantics(stack: Stack) -> None:
    user = await stack.user("onb-sql@example.com")
    user_id = UUID(user.user_id)
    store = stack.database.store.repositories().onboarding
    assert store is not None
    now = datetime.now(UTC)

    created = await asyncio.gather(*(store.get_or_create(user_id, now) for _ in range(5)))
    assert {state.created_at for state in created} == {created[0].created_at}  # одна строка

    assert await store.add_item(user_id, ChecklistItem.PROJECT_CREATED, ItemSource.SERVER, now)
    later = datetime.now(UTC)
    assert not await store.add_item(
        user_id, ChecklistItem.PROJECT_CREATED, ItemSource.CLIENT, later
    )
    items = await store.list_items(user_id)
    assert [(i.item, i.source, i.completed_at) for i in items] == [
        (ChecklistItem.PROJECT_CREATED, ItemSource.SERVER, now)
    ]
    results = await asyncio.gather(
        *(
            store.add_item(user_id, ChecklistItem.DIAGRAM_BUILT, ItemSource.SERVER, now)
            for _ in range(5)
        )
    )
    assert results.count(True) == 1  # гонка отметок: «впервые» — ровно один

    assert not await store.save_tour(
        user_id,
        expected_status=TourStatus.ACTIVE,
        status=TourStatus.COMPLETED,
        step=None,
        project_id=None,
        now=now,
    )
    assert await store.save_tour(
        user_id,
        expected_status=TourStatus.PENDING,
        status=TourStatus.ACTIVE,
        step=TourStepKey.RUN_WAIT,
        project_id=None,
        now=now,
    )
    state = await store.get_or_create(user_id, now)
    assert (state.tour_status, state.tour_step) == (TourStatus.ACTIVE, TourStepKey.RUN_WAIT)


async def test_runs_remember_author_and_survive_author_deletion(stack: Stack) -> None:
    user = await stack.user("onb-author@example.com")
    pid = (await user.post("/projects", json={"title": "Автор"})).json()["id"]
    await user.post(f"/projects/{pid}/sources/text", json={"content": "Принять заявку."})
    run = await _build(user, pid)
    select_author = text("SELECT created_by FROM runs WHERE id = :id")
    async with stack.database.sessions() as session:
        stored = (await session.execute(select_author, {"id": run["id"]})).scalar_one()
    assert str(stored) == user.user_id
    async with stack.database.sessions.begin() as session:
        await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user.user_id})
        remaining = (await session.execute(select_author, {"id": run["id"]})).scalar_one()
        items = (
            await session.execute(text("SELECT count(*) FROM user_onboarding_items"))
        ).scalar_one()
    assert remaining is None  # ON DELETE SET NULL
    assert items == 0  # пункты чек-листа удаляются вместе с пользователем


async def test_migration_0008_applies_and_rolls_back() -> None:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL не задан; PostgreSQL-интеграционный тест пропущен")
    schema = f"test_{uuid4().hex}"
    admin = create_async_engine(url)
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))

    def upgrade(sync_connection: Any, revision: str) -> None:
        config.attributes["connection"] = sync_connection
        command.upgrade(config, revision)

    def downgrade(sync_connection: Any, revision: str) -> None:
        config.attributes["connection"] = sync_connection
        command.downgrade(config, revision)

    def shape(sync_connection: Any) -> tuple[set[str], set[str]]:
        inspector = inspect(sync_connection)
        return (
            set(inspector.get_table_names()),
            {column["name"] for column in inspector.get_columns("runs")},
        )

    try:
        async with engine.begin() as connection:
            await connection.run_sync(upgrade, "head")
            tables, run_columns = await connection.run_sync(shape)
            assert {"user_onboarding", "user_onboarding_items"} <= tables
            assert "created_by" in run_columns
            await connection.run_sync(downgrade, "-1")
            tables, run_columns = await connection.run_sync(shape)
            assert not {"user_onboarding", "user_onboarding_items"} & tables
            assert "created_by" not in run_columns
            await connection.run_sync(upgrade, "head")
            tables, _ = await connection.run_sync(shape)
            assert "user_onboarding" in tables
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()
