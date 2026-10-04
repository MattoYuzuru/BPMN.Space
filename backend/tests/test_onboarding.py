"""Онбординг на in-memory хранилище: сервис, учёт действий, прогоны, мок-маркеры, материалы."""

import logging
from collections.abc import Iterator
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.container import Container, build_container
from app.domain.models import QuestionStatus, RunMode, RunStatus, SourceKind, SourceStatus
from app.domain.onboarding import (
    ChecklistItem,
    ItemSource,
    TargetHint,
    TargetRoute,
    TourStatus,
    TourStepKey,
)
from app.fixtures.samples import SAMPLES, TOUR_SAMPLE_ID, tour_text_suggestion
from app.main import create_app
from app.services.errors import ConflictError, InvalidInputError, NotFoundError
from tests.conftest import API, add_text, create_project, read_events

USER = uuid4()
OTHER = uuid4()


@pytest.fixture
def onboarding_settings() -> Settings:
    return Settings(
        mock_delay_scale=0,
        database_url=None,
        app_env="test",
        auth_enabled=True,
        rate_limit_enabled=False,
        seed_demo_data=True,
    )


@pytest.fixture
def box(onboarding_settings: Settings) -> Container:
    return build_container(onboarding_settings)


async def _items(box: Container, user: UUID = USER) -> list[ChecklistItem]:
    assert box.repos.onboarding is not None
    return [entry.item for entry in await box.repos.onboarding.list_items(user)]


# ---------- состояние тура ----------


async def test_state_is_created_lazily_with_defaults(box: Container) -> None:
    view = await box.onboarding.state(USER)
    assert view.state.tour_status is TourStatus.PENDING
    assert view.state.tour_step is None
    assert view.state.tour_project_id is None
    assert view.state.checklist_hidden is False
    assert view.items == []
    assert view.tour_text_suggestion == tour_text_suggestion()


async def test_full_tour_flow_with_logs(box: Container, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="app.services.onboarding")
    owned = await box.projects.create(title="Учебный", description=None, owner_id=USER)
    service = box.onboarding

    started = await service.update_tour(
        USER, status=TourStatus.ACTIVE, step=None, project_id=None, project_given=False
    )
    assert started.state.tour_status is TourStatus.ACTIVE
    assert started.state.tour_step is TourStepKey.PROJECT_CREATE

    moved = await service.update_tour(
        USER,
        status=None,
        step=TourStepKey.SOURCES_SAMPLE,
        project_id=owned.project.id,
        project_given=True,
    )
    assert moved.state.tour_step is TourStepKey.SOURCES_SAMPLE
    assert moved.state.tour_project_id == owned.project.id

    same = await service.update_tour(
        USER, status=None, step=TourStepKey.SOURCES_SAMPLE, project_id=None, project_given=False
    )
    assert same.state.tour_project_id == owned.project.id  # не переданный проект не сбрасывается

    done = await service.update_tour(
        USER, status=TourStatus.COMPLETED, step=None, project_id=None, project_given=False
    )
    assert done.state.tour_status is TourStatus.COMPLETED
    assert done.state.tour_step is None
    assert done.state.tour_project_id == owned.project.id

    names = [record.getMessage().split()[0] for record in caplog.records]
    assert names == ["onboarding.tour_started", "onboarding.step", "onboarding.tour_completed"]
    step_log = caplog.records[1].getMessage()
    assert "step=sources.sample" in step_log
    assert "previous_step=project.create" in step_log
    assert str(USER) in caplog.records[0].getMessage()


async def test_invalid_transitions_are_conflicts(box: Container) -> None:
    service = box.onboarding
    with pytest.raises(ConflictError):  # pending → completed
        await service.update_tour(
            USER, status=TourStatus.COMPLETED, step=None, project_id=None, project_given=False
        )
    with pytest.raises(ConflictError):  # смена шага вне тура
        await service.update_tour(
            USER, status=None, step=TourStepKey.RUN_START, project_id=None, project_given=False
        )
    await service.update_tour(
        USER, status=TourStatus.DISMISSED, step=None, project_id=None, project_given=False
    )
    with pytest.raises(ConflictError):  # dismissed → active только через restart
        await service.update_tour(
            USER, status=TourStatus.ACTIVE, step=None, project_id=None, project_given=False
        )
    with pytest.raises(ConflictError):  # dismissed → dismissed
        await service.update_tour(
            USER, status=TourStatus.DISMISSED, step=None, project_id=None, project_given=False
        )


async def test_tour_project_must_be_own(box: Container) -> None:
    mine = await box.projects.create(title="Мой", description=None, owner_id=USER)
    foreign = await box.projects.create(title="Чужой", description=None, owner_id=OTHER)
    await box.onboarding.update_tour(
        USER, status=TourStatus.ACTIVE, step=None, project_id=None, project_given=False
    )
    for project_id in (foreign.project.id, uuid4()):
        with pytest.raises(NotFoundError):
            await box.onboarding.update_tour(
                USER, status=None, step=None, project_id=project_id, project_given=True
            )
    cleared = await box.onboarding.update_tour(
        USER, status=None, step=None, project_id=mine.project.id, project_given=True
    )
    assert cleared.state.tour_project_id == mine.project.id
    cleared = await box.onboarding.update_tour(
        USER, status=None, step=None, project_id=None, project_given=True
    )
    assert cleared.state.tour_project_id is None


async def test_restart_from_every_status(box: Container, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="app.services.onboarding")
    owned = await box.projects.create(title="Учебный", description=None, owner_id=USER)
    service = box.onboarding
    await service.update_tour(
        USER,
        status=TourStatus.ACTIVE,
        step=TourStepKey.RUN_WAIT,
        project_id=owned.project.id,
        project_given=True,
    )
    await service.update_tour(
        USER, status=TourStatus.DISMISSED, step=None, project_id=None, project_given=False
    )
    restarted = await service.restart(USER)
    assert restarted.state.tour_status is TourStatus.ACTIVE
    assert restarted.state.tour_step is TourStepKey.PROJECT_CREATE
    assert restarted.state.tour_project_id is None
    again = await service.restart(USER)  # перезапуск работающего тура («Начать заново»)
    assert again.state.tour_status is TourStatus.ACTIVE
    assert "onboarding.tour_dismissed" in " ".join(r.getMessage() for r in caplog.records)
    assert "restart=true" in caplog.records[-1].getMessage()


async def test_deleting_tour_project_clears_reference(box: Container) -> None:
    owned = await box.projects.create(title="Учебный", description=None, owner_id=USER)
    await box.onboarding.update_tour(
        USER, status=TourStatus.ACTIVE, step=None, project_id=owned.project.id, project_given=True
    )
    await box.projects.delete(owned.project.id)
    assert (await box.onboarding.state(USER)).state.tour_project_id is None


async def test_checklist_hidden_toggle(box: Container) -> None:
    hidden = await box.onboarding.set_checklist_hidden(USER, hidden=True)
    assert hidden.state.checklist_hidden is True
    shown = await box.onboarding.set_checklist_hidden(USER, hidden=False)
    assert shown.state.checklist_hidden is False


# ---------- учёт пунктов ----------


async def test_record_is_idempotent_and_keeps_first_timestamp(box: Container) -> None:
    assert await box.onboarding.record(USER, ChecklistItem.PROJECT_CREATED) is True
    first = (await box.onboarding.state(USER)).items[0]
    assert await box.onboarding.record(USER, ChecklistItem.PROJECT_CREATED) is False
    after = (await box.onboarding.state(USER)).items
    assert len(after) == 1
    assert after[0].completed_at == first.completed_at
    assert after[0].source is ItemSource.SERVER


async def test_record_logs_only_first_completion(
    box: Container, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="app.services.onboarding")
    await box.onboarding.record(USER, ChecklistItem.TEXT_SOURCE_ADDED)
    await box.onboarding.record(USER, ChecklistItem.TEXT_SOURCE_ADDED)
    messages = [r.getMessage() for r in caplog.records]
    assert len(messages) == 1
    assert messages[0].startswith("onboarding.item_completed")
    assert "item=text_source_added" in messages[0]
    assert "source=server" in messages[0]
    assert "in_tour=false" in messages[0]


async def test_record_inside_active_tour_is_marked_in_tour(
    box: Container, caplog: pytest.LogCaptureFixture
) -> None:
    await box.onboarding.update_tour(
        USER, status=TourStatus.ACTIVE, step=None, project_id=None, project_given=False
    )
    caplog.set_level(logging.INFO, logger="app.services.onboarding")
    await box.onboarding.record(USER, ChecklistItem.PROJECT_CREATED)
    assert "in_tour=true" in caplog.records[-1].getMessage()


async def test_record_without_user_or_when_disabled_does_nothing() -> None:
    off = build_container(Settings(mock_delay_scale=0, auth_enabled=True, onboarding_enabled=False))
    no_auth = build_container(Settings(mock_delay_scale=0, auth_enabled=False))
    for container in (off, no_auth):
        assert container.onboarding.enabled is False
        assert await container.onboarding.record(USER, ChecklistItem.PROJECT_CREATED) is False
        assert container.repos.onboarding is not None
        assert await container.repos.onboarding.list_items(USER) == []
    box = build_container(Settings(mock_delay_scale=0, auth_enabled=True))
    assert await box.onboarding.record(None, ChecklistItem.PROJECT_CREATED) is False


async def test_record_never_raises_when_storage_fails(
    box: Container, caplog: pytest.LogCaptureFixture
) -> None:
    store = box.repos.onboarding
    assert store is not None

    async def boom(*_: object, **__: object) -> bool:
        raise RuntimeError("БД недоступна")

    store.add_item = boom  # type: ignore[method-assign]
    assert await box.onboarding.record(USER, ChecklistItem.PROJECT_CREATED) is False
    assert "Не удалось отметить пункт" in caplog.text


async def test_client_events_are_whitelisted_and_idempotent(box: Container) -> None:
    await box.onboarding.report_event(USER, ChecklistItem.SIMULATION_RUN)
    await box.onboarding.report_event(USER, ChecklistItem.SIMULATION_RUN)
    items = (await box.onboarding.state(USER)).items
    assert [(i.item, i.source) for i in items] == [
        (ChecklistItem.SIMULATION_RUN, ItemSource.CLIENT)
    ]
    for item in ChecklistItem:
        if item in {ChecklistItem.SIMULATION_RUN, ChecklistItem.DIAGRAM_EXPORTED}:
            continue
        with pytest.raises(InvalidInputError):
            await box.onboarding.report_event(USER, item)


# ---------- точки учёта в ручках (auth выключен в HTTP-клиенте, поэтому вызываем сервис) ----------


async def test_run_marks_the_person_who_started_it(box: Container) -> None:
    owner, editor = USER, OTHER
    view = await box.projects.create(title="Процесс", description=None, owner_id=owner)
    project_id = view.project.id
    await box.sources.create_text(
        project_id,
        content="1. Принять заявку. Ответственный: оператор.",
        title=None,
        kind=SourceKind.TEXT,
        duration_sec=None,
    )
    run = await box.runs.start(project_id, mode=RunMode.BUILD, created_by=editor)
    await box.spawner.wait_idle()
    assert (await box.runs.get(run.id)).status is RunStatus.SUCCEEDED
    assert await _items(box, editor) == [ChecklistItem.DIAGRAM_BUILT]
    assert await _items(box, owner) == []


async def test_analyze_and_failed_runs_do_not_mark_diagram_built(box: Container) -> None:
    view = await box.projects.create(title="Процесс", description=None, owner_id=USER)
    project_id = view.project.id
    await box.sources.create_text(
        project_id,
        content="1. Принять заявку. Ответственный: оператор.",
        title=None,
        kind=SourceKind.TEXT,
        duration_sec=None,
    )
    await box.runs.start(project_id, mode=RunMode.ANALYZE, created_by=USER)
    await box.spawner.wait_idle()
    await box.sources.create_text(
        project_id,
        content="[[mock:fail-structuring]]",
        title=None,
        kind=SourceKind.TEXT,
        duration_sec=None,
    )
    failed = await box.runs.start(project_id, mode=RunMode.BUILD, created_by=USER)
    await box.spawner.wait_idle()
    assert (await box.runs.get(failed.id)).status is RunStatus.FAILED
    assert await _items(box) == []


async def test_run_without_author_marks_nothing(box: Container) -> None:
    view = await box.projects.create(title="Процесс", description=None)
    await box.sources.create_text(
        view.project.id,
        content="1. Принять заявку. Ответственный: оператор.",
        title=None,
        kind=SourceKind.TEXT,
        duration_sec=None,
    )
    await box.runs.start(view.project.id, mode=RunMode.BUILD)
    await box.spawner.wait_idle()
    assert await box.repos.onboarding.list_items(USER) == []  # type: ignore[union-attr]


async def test_rebuild_after_answer_marks_rebuilt_once_per_condition(box: Container) -> None:
    service = box.sources
    view = await box.projects.create(title="Тур", description=None, owner_id=USER)
    project_id = view.project.id
    source, _ = await box.samples.add(project_id, TOUR_SAMPLE_ID)
    await service.process_file(source.id)
    run = await box.runs.start(project_id, mode=RunMode.BUILD, created_by=USER)
    await box.spawner.wait_idle()
    assert (await box.runs.get(run.id)).status is RunStatus.SUCCEEDED
    assert await _items(box) == [ChecklistItem.DIAGRAM_BUILT]  # первой схемы ещё не было

    question = (await box.questions.list(project_id, status=QuestionStatus.OPEN))[0]
    await box.questions.answer(question.id, text="Акт готовит инженер, выезжавший на осмотр.")
    await box.runs.start(project_id, mode=RunMode.BUILD, created_by=USER)
    await box.spawner.wait_idle()
    assert await _items(box) == [ChecklistItem.DIAGRAM_BUILT, ChecklistItem.DIAGRAM_REBUILT]


async def test_rebuild_without_new_answer_is_not_rebuilt(box: Container) -> None:
    view = await box.projects.create(title="Процесс", description=None, owner_id=USER)
    await box.sources.create_text(
        view.project.id,
        content="1. Принять заявку. Ответственный: оператор.",
        title=None,
        kind=SourceKind.TEXT,
        duration_sec=None,
    )
    for _ in range(2):
        await box.runs.start(view.project.id, mode=RunMode.BUILD, created_by=USER)
        await box.spawner.wait_idle()
    assert await _items(box) == [ChecklistItem.DIAGRAM_BUILT]


async def test_progress_failure_does_not_fail_the_run(
    box: Container, caplog: pytest.LogCaptureFixture
) -> None:
    class Broken:
        async def record(self, user_id: UUID | None, item: ChecklistItem) -> bool:
            raise RuntimeError("учёт сломан")

    box.runs._progress = Broken()
    view = await box.projects.create(title="Процесс", description=None, owner_id=USER)
    await box.sources.create_text(
        view.project.id,
        content="1. Принять заявку. Ответственный: оператор.",
        title=None,
        kind=SourceKind.TEXT,
        duration_sec=None,
    )
    run = await box.runs.start(view.project.id, mode=RunMode.BUILD, created_by=USER)
    await box.spawner.wait_idle()
    assert (await box.runs.get(run.id)).status is RunStatus.SUCCEEDED
    assert "не удалось отметить прогресс" in caplog.text


# ---------- выбор места по реальным проектам ----------


async def test_target_ignores_demo_projects_and_foreign_projects(box: Container) -> None:
    target = await box.onboarding.target(USER, ChecklistItem.DIAGRAM_EDITED)
    assert (target.route, target.hint, target.project_id) == (
        TargetRoute.PROJECTS,
        TargetHint.NEED_PROJECT,
        None,
    )
    await box.projects.create(title="Чужой", description=None, owner_id=OTHER)
    target = await box.onboarding.target(USER, ChecklistItem.TEXT_SOURCE_ADDED)
    assert target.route is TargetRoute.PROJECTS


async def test_target_follows_project_state(box: Container) -> None:
    view = await box.projects.create(title="Свой", description=None, owner_id=USER)
    project_id = view.project.id
    target = await box.onboarding.target(USER, ChecklistItem.TEXT_SOURCE_ADDED)
    assert (target.project_id, target.hint) == (project_id, TargetHint.DO_ITEM)
    target = await box.onboarding.target(USER, ChecklistItem.DIAGRAM_BUILT)
    assert target.hint is TargetHint.NEED_SOURCE

    source, _ = await box.samples.add(project_id, TOUR_SAMPLE_ID)
    await box.sources.process_file(source.id)
    target = await box.onboarding.target(USER, ChecklistItem.DIAGRAM_BUILT)
    assert (target.project_id, target.hint) == (project_id, TargetHint.DO_ITEM)
    target = await box.onboarding.target(USER, ChecklistItem.DIAGRAM_EXPORTED)
    assert target.hint is TargetHint.NEED_DIAGRAM
    target = await box.onboarding.target(USER, ChecklistItem.QUESTION_ANSWERED)
    assert target.hint is TargetHint.NEED_QUESTIONS

    await box.runs.start(project_id, mode=RunMode.BUILD, created_by=USER)
    await box.spawner.wait_idle()
    opened = await box.questions.list(project_id, status=QuestionStatus.OPEN)
    target = await box.onboarding.target(USER, ChecklistItem.ASSUMPTION_ACCEPTED)
    assert (target.hint, target.question_id) == (TargetHint.DO_ITEM, opened[0].id)
    target = await box.onboarding.target(USER, ChecklistItem.SIMULATION_RUN)
    assert (target.hint, target.project_id) == (TargetHint.DO_ITEM, project_id)
    target = await box.onboarding.target(USER, ChecklistItem.DIAGRAM_REBUILT)
    assert target.question_id == opened[0].id  # ответа ещё нет — ведём к вопросу

    await box.questions.answer(opened[0].id, text="Акт готовит инженер.")
    target = await box.onboarding.target(USER, ChecklistItem.DIAGRAM_REBUILT)
    assert (target.hint, target.question_id) == (TargetHint.DO_ITEM, None)


async def test_target_earliest_open_question_and_sorting_by_updated_at(box: Container) -> None:
    older = await box.projects.create(title="Старый", description=None, owner_id=USER)
    newer = await box.projects.create(title="Новый", description=None, owner_id=USER)
    await box.repos.projects.touch(older.project.id, newer.project.updated_at + timedelta(hours=1))
    target = await box.onboarding.target(USER, ChecklistItem.VOICE_ADDED)
    assert target.project_id == older.project.id


# ---------- учебные материалы и мок-маркеры (через HTTP, auth выключен) ----------


@pytest.fixture
def api(settings: Settings, container: Container) -> Iterator[TestClient]:
    with TestClient(create_app(settings, container=container)) as test_client:
        yield test_client


def test_samples_list_matches_registry(api: TestClient) -> None:
    response = api.get(f"{API}/samples")
    assert response.status_code == 200
    samples = response.json()
    assert [s["id"] for s in samples] == [s.id for s in SAMPLES]
    tour = [s for s in samples if s["tour"]]
    assert len(tour) == 1
    assert tour[0]["title"] == "Записка со встречи — техприсоединение.docx"
    assert tour[0]["format"] == "docx"
    assert tour[0]["kind"] == "document"
    assert all(s["size_bytes"] > 0 for s in samples)
    voice = next(s for s in samples if s["kind"] == "voice")
    assert voice["format"] == "voice"
    assert 900 <= voice["size_bytes"] <= 1100  # расшифровка ≈ 550 символов в UTF-8


def _wait_ready(api: TestClient, project_id: str) -> list[dict[str, object]]:
    detail = api.get(f"{API}/projects/{project_id}").json()
    return detail["sources"]


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda s: s.id)
def test_every_sample_becomes_a_ready_source(api: TestClient, sample) -> None:
    project_id = create_project(api)
    response = api.post(
        f"{API}/projects/{project_id}/sources/sample", json={"sample_id": sample.id}
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["title"] == sample.title
    sources = _wait_ready(api, project_id)
    assert len(sources) == 1
    assert sources[0]["status"] == SourceStatus.READY.value
    assert str(sources[0]["content"]).strip()
    if sample.kind.value == "voice":
        assert sources[0]["kind"] == SourceKind.VOICE.value
        assert sources[0]["file_name"] is None
    else:
        assert sources[0]["kind"] == SourceKind.FILE.value
        assert sources[0]["file_name"] == sample.title


def test_tour_docx_is_parsed_by_current_parser(api: TestClient) -> None:
    project_id = create_project(api)
    api.post(f"{API}/projects/{project_id}/sources/sample", json={"sample_id": TOUR_SAMPLE_ID})
    content = str(_wait_ready(api, project_id)[0]["content"])
    assert "Записка со встречи" in content
    assert "мы обычно укладываемся в пять рабочих дней" in content
    assert "Осмотр делаем одним выездом вместе с монтёрами учёта" in content
    assert "кто готовит его проект" in content
    assert content.count("\n") == 2  # заголовок, записка, дополнение — три абзаца


def test_sample_errors(api: TestClient) -> None:
    project_id = create_project(api)
    assert (
        api.post(
            f"{API}/projects/{project_id}/sources/sample", json={"sample_id": "нет"}
        ).status_code
        == 404
    )
    assert (
        api.post(f"{API}/projects/{project_id}/sources/sample", json={"sample_id": ""}).status_code
        == 422
    )
    missing = uuid4()
    assert (
        api.post(
            f"{API}/projects/{missing}/sources/sample", json={"sample_id": TOUR_SAMPLE_ID}
        ).status_code
        == 404
    )


def _run(api: TestClient, project_id: str, mode: str = "build") -> tuple[dict[str, object], list]:
    started = api.post(f"{API}/projects/{project_id}/runs", json={"mode": mode})
    assert started.status_code == 202, started.text
    run_id = started.json()["id"]
    events = read_events(api, run_id)
    return events[-1][1]["run"], events


def _open_questions(api: TestClient, project_id: str) -> list[dict[str, object]]:
    return api.get(f"{API}/projects/{project_id}/questions", params={"status": "open"}).json()


def test_tour_materials_give_exactly_two_open_questions_and_a_diagram(api: TestClient) -> None:
    project_id = create_project(api, "Мой первый процесс")
    api.post(f"{API}/projects/{project_id}/sources/sample", json={"sample_id": TOUR_SAMPLE_ID})
    add_text(api, project_id, tour_text_suggestion())
    run, events = _run(api, project_id)
    assert run["status"] == "succeeded", run
    assert len(_open_questions(api, project_id)) == 2
    detail = api.get(f"{API}/projects/{project_id}").json()
    assert detail["latest_version"] is not None
    assert any(kind == "version" for kind, _ in events)


def test_tour_materials_with_voice_sample_still_give_two_questions(api: TestClient) -> None:
    project_id = create_project(api)
    api.post(f"{API}/projects/{project_id}/sources/sample", json={"sample_id": TOUR_SAMPLE_ID})
    add_text(api, project_id, tour_text_suggestion())
    api.post(
        f"{API}/projects/{project_id}/sources/sample", json={"sample_id": "voice-request-approval"}
    )
    run, _ = _run(api, project_id)
    assert run["status"] == "succeeded"
    assert len(_open_questions(api, project_id)) == 2


def test_tour_document_alone_gives_two_questions(api: TestClient) -> None:
    project_id = create_project(api)
    api.post(f"{API}/projects/{project_id}/sources/sample", json={"sample_id": TOUR_SAMPLE_ID})
    run, _ = _run(api, project_id)
    assert run["status"] == "succeeded"
    assert len(_open_questions(api, project_id)) == 2


MARKER_TEXT = "Заявитель подаёт заявку через личный кабинет. Специалист проверяет документы."


def test_marker_fail_structuring_fails_after_questions_were_created(api: TestClient) -> None:
    project_id = create_project(api)
    add_text(api, project_id, f"{MARKER_TEXT}\n[[mock:fail-structuring]]")
    run, events = _run(api, project_id)
    assert run["status"] == "failed"
    assert run["error"]
    stages = [data["stage"] for kind, data in events if kind == "stage"]
    assert stages[-1] == "structuring"
    assert "reconciling" in stages
    assert len(_open_questions(api, project_id)) > 0
    assert api.get(f"{API}/projects/{project_id}").json()["latest_version"] is None


def test_marker_fail_early_fails_on_extracting_without_questions(api: TestClient) -> None:
    project_id = create_project(api)
    add_text(api, project_id, f"{MARKER_TEXT}\n[[mock:fail-early]]")
    run, events = _run(api, project_id)
    assert run["status"] == "failed"
    stages = [data["stage"] for kind, data in events if kind == "stage"]
    assert stages[-1] == "extracting"
    assert _open_questions(api, project_id) == []


def test_marker_no_questions_builds_diagram_without_questions(api: TestClient) -> None:
    project_id = create_project(api)
    add_text(api, project_id, f"{MARKER_TEXT}\n[[mock:no-questions]]")
    run, _ = _run(api, project_id)
    assert run["status"] == "succeeded"
    assert api.get(f"{API}/projects/{project_id}/questions").json() == []
    assert api.get(f"{API}/projects/{project_id}").json()["latest_version"] is not None


def test_without_marker_the_same_text_asks_questions(api: TestClient) -> None:
    project_id = create_project(api)
    add_text(api, project_id, MARKER_TEXT)
    run, _ = _run(api, project_id)
    assert run["status"] == "succeeded"
    assert len(_open_questions(api, project_id)) == 2  # типовые вопросы mock-модели


def test_markers_do_not_leak_into_diagram_steps(api: TestClient) -> None:
    project_id = create_project(api)
    add_text(api, project_id, f"{MARKER_TEXT}\n[[mock:no-questions]]")
    _run(api, project_id)
    version_id = api.get(f"{API}/projects/{project_id}").json()["latest_version"]["id"]
    xml = api.get(f"{API}/versions/{version_id}/xml").text
    assert "mock:" not in xml


# ---------- ручки без аккаунтов ----------


def test_onboarding_endpoints_without_accounts(api: TestClient) -> None:
    state = api.get(f"{API}/me/onboarding")
    assert state.status_code == 200
    assert state.json()["enabled"] is False
    assert state.json()["tour"] is None
    for method, path, body in (
        ("PATCH", "/me/onboarding/tour", {"status": "dismissed"}),
        ("POST", "/me/onboarding/tour/restart", None),
        ("PATCH", "/me/onboarding/checklist", {"hidden": True}),
        ("POST", "/me/onboarding/events", {"item": "simulation_run"}),
        ("GET", "/me/onboarding/items/project_shared/target", None),
    ):
        response = api.request(method, f"{API}{path}", json=body)
        assert response.status_code == 404, (path, response.text)


def test_main_actions_work_when_onboarding_is_off(api: TestClient) -> None:
    project_id = create_project(api)
    add_text(api, project_id, MARKER_TEXT)
    run, _ = _run(api, project_id)
    assert run["status"] == "succeeded"
