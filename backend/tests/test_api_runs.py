"""Прогоны: запуск, SSE-поток, сверка вопросов на демо-проекте, сборка версии, конфликты."""

import asyncio

from fastapi.testclient import TestClient

from app.container import Container
from app.domain.models import RunStage
from app.infra.seed import seed_id
from tests.conftest import API, DEMO, add_text, create_project, read_events


def _questions(client: TestClient) -> dict[str, dict[str, object]]:
    return {q["code"]: q for q in client.get(f"{API}/projects/{DEMO}/questions").json()}


def test_analyze_demo_streams_stages_questions_summary_done(client: TestClient) -> None:
    response = client.post(f"{API}/projects/{DEMO}/runs", json={"mode": "analyze"})
    assert response.status_code == 202
    run = response.json()
    assert run["status"] in {"queued", "running", "succeeded"}

    events = read_events(client, run["id"])
    kinds = [kind for kind, _ in events]
    assert kinds == [
        "stage",
        "stage",
        "stage",
        "question",
        "question",
        "question",
        "summary",
        "done",
    ]
    stages = [data["stage"] for kind, data in events if kind == "stage"]
    assert stages == ["reading_sources", "extracting", "reconciling"]
    assert events[0][1]["label"] == "Читаю источники"
    progress = [data["progress"] for kind, data in events if kind == "stage"]
    assert progress == sorted(progress)

    changed = {
        data["question"]["code"]: data["question"] for kind, data in events if kind == "question"
    }
    assert changed["Q-5"]["status"] == "resolved"  # ответ подтверждён
    assert changed["Q-3"]["status"] == "resolved"  # «Финансы проекта.docx» закрыл вопрос
    assert "финансовый отдел" in changed["Q-3"]["evidence"]["quote"]
    assert changed["Q-7"]["status"] == "open"
    assert changed["Q-7"]["kind"] == "conflict"
    assert changed["Q-7"]["about"]["source_id"] == str(seed_id("tp861/source/finances"))

    summary = events[-2][1]
    assert summary == {"resolved": 2, "open": 2, "new": 1, "ignored": 1, "answered": 0}
    done = events[-1][1]["run"]
    assert done["status"] == "succeeded"
    assert done["progress"] == 1
    assert done["stage_label"] == "Готово"
    assert done["summary"] == summary

    questions = _questions(client)
    assert questions["Q-4"]["status"] == "open"
    assert questions["Q-6"]["status"] == "open"
    assert questions["Q-2"]["status"] == "ignored"

    detail = client.get(f"{API}/projects/{DEMO}").json()
    assert detail["active_run"] is None
    assert detail["summary"]["new"] == 1
    assert detail["status"] == "needs_answers"


def test_build_creates_new_version_with_finance_lane(client: TestClient) -> None:
    run = client.post(f"{API}/projects/{DEMO}/runs", json={"mode": "build"}).json()
    events = read_events(client, run["id"])
    stages = [data["stage"] for kind, data in events if kind == "stage"]
    assert stages == [
        "reading_sources",
        "extracting",
        "reconciling",
        "structuring",
        "validating",
        "layout",
    ]
    version = next(data["version"] for kind, data in events if kind == "version")
    assert version["number"] == 3
    assert version["origin"] == "generated"
    assert "Финансовый отдел" in version["lanes"]
    assert version["diff"] == {"added": 3, "removed": 0, "changed": 2}
    assert version["report"]["xsd_valid"] is True
    assert version["trace"]["Task_IssueInvoice"]["source_id"] == str(
        seed_id("tp861/source/finances")
    )
    done = events[-1][1]["run"]
    assert done["version_id"] == version["id"]

    detail = client.get(f"{API}/projects/{DEMO}").json()
    assert detail["latest_version"]["id"] == version["id"]
    assert detail["counts"]["versions"] == 3
    assert detail["lanes"] == version["lanes"]


def test_second_run_while_active_conflicts(client: TestClient, container: Container) -> None:
    project_id = create_project(client)
    add_text(client, project_id, "Оператор принимает заявку. Руководитель согласует заявку.")
    gate = asyncio.Event()

    async def hold(_stage: RunStage) -> None:
        await gate.wait()

    container.runs._pace = hold
    first = client.post(f"{API}/projects/{project_id}/runs", json={"mode": "analyze"})
    assert first.status_code == 202
    second = client.post(f"{API}/projects/{project_id}/runs", json={"mode": "build"})
    assert second.status_code == 409
    assert "уже идёт" in second.json()["detail"]
    assert client.get(f"{API}/projects/{project_id}").json()["status"] == "analyzing"
    assert client.delete(f"{API}/projects/{project_id}").status_code == 409
    assert client.portal is not None
    client.portal.call(gate.set)
    events = read_events(client, first.json()["id"])
    assert events[-1][0] == "done"


def test_run_requires_sources(client: TestClient) -> None:
    project_id = create_project(client)
    response = client.post(f"{API}/projects/{project_id}/runs", json={"mode": "analyze"})
    assert response.status_code == 409
    assert response.json()["detail"] == "Добавьте хотя бы один источник с текстом"


def test_run_validation_and_not_found(client: TestClient) -> None:
    missing = "00000000-0000-0000-0000-000000000000"
    assert client.post(f"{API}/projects/{missing}/runs", json={"mode": "build"}).status_code == 404
    bad = client.post(f"{API}/projects/{DEMO}/runs", json={"mode": "deploy"})
    assert bad.status_code == 422
    assert bad.json()["detail"].startswith("Некорректный запрос")
    assert client.get(f"{API}/runs/{missing}").status_code == 404
    assert client.get(f"{API}/runs/{missing}/events").status_code == 404
    assert client.get(f"{API}/runs/not-a-uuid").status_code == 422


def test_generic_project_gets_questions_and_linear_diagram(client: TestClient) -> None:
    project_id = create_project(client, "Приём заявки")
    text = (
        "Порядок действий:\n"
        "1. Принять заявку. Ответственный: оператор.\n"
        "2. Проверить документы. Ответственный: оператор.\n"
        "3. Согласовать заявку. Ответственный: руководитель."
    )
    add_text(client, project_id, text)
    analyze = client.post(f"{API}/projects/{project_id}/runs", json={"mode": "analyze"}).json()
    events = read_events(client, analyze["id"])
    created = [data["question"] for kind, data in events if kind == "question"]
    assert [q["code"] for q in created] == ["Q-1", "Q-2"]
    assert created[0]["about"]["quote"] == "Принять заявку"
    assert created[0]["element_ids"] == ["Task_1"]

    build = client.post(f"{API}/projects/{project_id}/runs", json={"mode": "build"}).json()
    events = read_events(client, build["id"])
    version = next(data["version"] for kind, data in events if kind == "version")
    assert version["lanes"] == ["Оператор", "Руководитель"]
    assert {a["element_id"] for a in version["report"]["assumptions"]} == {"Task_1", "Task_3"}
    assert version["report"]["lint"] == []


def test_failed_run_emits_error_then_done(client: TestClient) -> None:
    project_id = create_project(client)
    add_text(client, project_id, "Коротко.")
    run = client.post(f"{API}/projects/{project_id}/runs", json={"mode": "build"}).json()
    events = read_events(client, run["id"])
    assert [kind for kind, _ in events][-2:] == ["error", "done"]
    assert "шаги процесса" in events[-2][1]["message"]
    final = client.get(f"{API}/runs/{run['id']}").json()
    assert final["status"] == "failed"
    assert final["stage_label"] == "Ошибка"
    assert final["error"] == events[-2][1]["message"]


def test_events_of_seed_run_and_resume(client: TestClient) -> None:
    seeded = str(seed_id("tp861/run/4"))
    events = read_events(client, seeded)
    assert [kind for kind, _ in events] == ["done"]
    assert events[0][1]["run"]["version_id"] == str(seed_id("tp861/version/2"))
    assert read_events(client, seeded, **{"Last-Event-ID": "1"}) == []

    run = client.post(f"{API}/projects/{DEMO}/runs", json={"mode": "analyze"}).json()
    full = read_events(client, run["id"])
    tail = read_events(client, run["id"], **{"Last-Event-ID": "6"})
    assert tail == full[6:]
