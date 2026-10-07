"""Проекты: список с курсором и поиском, карточка, создание, правка, удаление, примеры."""

import asyncio
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.container import Container
from app.domain.bpmn.document import parse_bpmn
from app.fixtures.complex_examples import COMPLEX_EXAMPLES
from tests.conftest import API, DEMO, create_project, read_events

MISSING = "00000000-0000-0000-0000-000000000000"


def test_list_paginates_through_all_seed_projects(client: TestClient) -> None:
    first = client.get(f"{API}/projects", params={"limit": 3}).json()
    assert first["total"] == 5
    assert len(first["items"]) == 3
    assert first["items"][0]["id"] == DEMO  # демо-проект изменён последним
    seen = [item["id"] for item in first["items"]]
    cursor = first["next_cursor"]
    while cursor:
        page = client.get(f"{API}/projects", params={"limit": 20, "cursor": cursor}).json()
        seen += [item["id"] for item in page["items"]]
        cursor = page["next_cursor"]
    assert len(seen) == len(set(seen)) == 5
    statuses = {item["status"] for item in first["items"]}
    assert {"needs_answers", "ready"} <= statuses


def test_list_card_fields(client: TestClient) -> None:
    demo = client.get(f"{API}/projects", params={"q": "присоединение к электросетям"}).json()
    assert demo["total"] == 1
    card = demo["items"][0]
    assert card["counts"] == {
        "sources": 3,
        "questions_open": 3,
        "questions_resolved": 1,
        "versions": 2,
    }
    assert card["lanes"] == ["Заявитель", "Сетевая организация", "Гарантирующий поставщик"]
    assert card["status"] == "needs_answers"


def test_search_is_case_and_yo_insensitive(client: TestClient) -> None:
    result = client.get(f"{API}/projects", params={"q": "НАРЯДУ-ДОПУСКУ"}).json()
    assert [item["title"] for item in result["items"]] == [
        "Работы в электроустановках по наряду-допуску"
    ]
    assert client.get(f"{API}/projects", params={"q": "РАБОТЫ"}).json()["total"] == 1
    empty = client.get(f"{API}/projects", params={"q": "нет такого"}).json()
    assert empty == {"items": [], "next_cursor": None, "total": 0}


def test_list_rejects_bad_cursor_and_limit(client: TestClient) -> None:
    bad = client.get(f"{API}/projects", params={"cursor": "мусор"})
    assert bad.status_code == 422
    assert bad.json() == {"detail": "Некорректный курсор"}
    assert client.get(f"{API}/projects", params={"limit": 0}).status_code == 422
    assert client.get(f"{API}/projects", params={"limit": 101}).status_code == 422


def test_project_detail(client: TestClient) -> None:
    detail = client.get(f"{API}/projects/{DEMO}").json()
    assert detail["title"] == "Технологическое присоединение к электросетям"
    kinds = [s["kind"] for s in detail["sources"]]
    assert kinds == ["text", "voice", "answer", "file"]
    assert [q["status"] for q in detail["questions"]] == [
        "resolved",
        "ignored",
        "open",
        "open",
        "answered",
        "open",
    ]
    assert detail["latest_version"]["number"] == 2
    assert "xml" not in detail["latest_version"]
    assert detail["active_run"] is None
    assert detail["summary"] == {"resolved": 1, "open": 3, "new": 0, "ignored": 1, "answered": 1}
    resolved = detail["questions"][0]
    assert resolved["evidence"]["quote"].startswith("Уведомление о недостающих документах")


def test_create_update_delete_project(client: TestClient) -> None:
    created = client.post(
        f"{API}/projects", json={"title": "  Новый   процесс ", "description": "Описание"}
    )
    assert created.status_code == 201
    project = created.json()
    assert project["title"] == "Новый процесс"
    assert project["status"] == "empty"
    assert project["counts"] == {
        "sources": 0,
        "questions_open": 0,
        "questions_resolved": 0,
        "versions": 0,
    }
    listed = client.get(f"{API}/projects", params={"limit": 1}).json()
    assert listed["items"][0]["id"] == project["id"]

    patched = client.patch(f"{API}/projects/{project['id']}", json={"description": None})
    assert patched.status_code == 200
    assert patched.json()["description"] is None
    assert patched.json()["title"] == "Новый процесс"
    renamed = client.patch(f"{API}/projects/{project['id']}", json={"title": "Другое"}).json()
    assert renamed["title"] == "Другое"

    assert client.delete(f"{API}/projects/{project['id']}").status_code == 204
    assert client.get(f"{API}/projects/{project['id']}").status_code == 404
    assert client.delete(f"{API}/projects/{project['id']}").status_code == 404


def test_delete_project_removes_uploaded_files(client: TestClient, container: Container) -> None:
    project_id = create_project(client, "Проект с файлом")
    response = client.post(
        f"{API}/projects/{project_id}/sources/file",
        files={"file": ("source.txt", b"content", "text/plain")},
    )
    assert response.status_code == 201
    source_id = response.json()["id"]
    source = asyncio.run(container.repos.sources.get(UUID(source_id)))
    assert source is not None
    assert source.file_key
    assert asyncio.run(container.storage.load(source.file_key)) == b"content"

    assert client.delete(f"{API}/projects/{project_id}").status_code == 204
    with pytest.raises(KeyError):
        asyncio.run(container.storage.load(source.file_key))


def test_create_validation(client: TestClient) -> None:
    empty = client.post(f"{API}/projects", json={"title": ""})
    assert empty.status_code == 422
    assert empty.json() == {"detail": "Некорректный запрос: «title» — слишком короткое значение"}
    blank = client.post(f"{API}/projects", json={"title": "   "})
    assert blank.status_code == 422
    assert blank.json() == {"detail": "Название проекта не может быть пустым"}
    missing = client.post(f"{API}/projects", json={})
    assert missing.json() == {"detail": "Некорректный запрос: «title» — обязательное поле"}
    assert client.patch(f"{API}/projects/{MISSING}", json={"title": "x"}).status_code == 404


def test_examples_and_project_from_example(client: TestClient) -> None:
    examples = client.get(f"{API}/examples").json()
    assert [e["id"] for e in examples] == [
        "tp861",
        "work-permit",
        "energy-incident",
        "logistics-order",
        "service-release",
    ]
    assert all(e["content"] and e["description"] for e in examples)

    created = client.post(f"{API}/projects/from-example", json={"example_id": "energy-incident"})
    assert created.status_code == 201
    project = created.json()
    assert project["status"] == "ready"
    assert project["counts"]["sources"] == 1
    detail = client.get(f"{API}/projects/{project['id']}").json()
    assert detail["sources"][0]["title"].startswith("Восстановление энергоснабжения")
    assert len(detail["sources"][0]["content"]) > 10_000

    missing = client.post(f"{API}/projects/from-example", json={"example_id": "nope"})
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Пример не найден"}


@pytest.mark.parametrize("example", COMPLEX_EXAMPLES, ids=lambda example: example.key)
def test_complex_example_copy_builds_full_recorded_graph_without_invented_gaps(
    client: TestClient, example
) -> None:
    copied = client.post(f"{API}/projects/from-example", json={"example_id": example.key}).json()
    run = client.post(f"{API}/projects/{copied['id']}/runs", json={"mode": "build"}).json()
    events = read_events(client, run["id"])
    assert events[-1][0] == "done"
    assert events[-1][1]["run"]["status"] == "succeeded"
    assert not [event for event in events if event[0] == "question"]
    version = next(data["version"] for kind, data in events if kind == "version")
    xml = client.get(f"{API}/versions/{version['id']}/xml").text
    document = parse_bpmn(xml)
    assert len(document.nodes) == example.nodes
    tasks = [node for node in document.nodes.values() if node.type.endswith("Task")]
    assert len(version["trace"]) == len(tasks)


def test_unknown_route_has_russian_detail(client: TestClient) -> None:
    response = client.get(f"{API}/nothing")
    assert response.status_code == 404
    assert response.json() == {"detail": "Не найдено"}
    assert client.put(f"{API}/projects").status_code == 405


def test_project_created_in_example_flows_through_runs(client: TestClient) -> None:
    project_id = client.post(f"{API}/projects/from-example", json={"example_id": "tp861"}).json()[
        "id"
    ]
    run = client.post(f"{API}/projects/{project_id}/runs", json={"mode": "analyze"}).json()
    events = read_events(client, run["id"])
    codes = [data["question"]["code"] for kind, data in events if kind == "question"]
    assert codes == ["Q-1", "Q-2", "Q-3", "Q-4"]
    build = client.post(f"{API}/projects/{project_id}/runs", json={"mode": "build"}).json()
    events = read_events(client, build["id"])
    version = next(data["version"] for kind, data in events if kind == "version")
    assert version["number"] == 1
    assert {"Task_NotifyMissing", "Gateway_Power"} <= {
        a["element_id"] for a in version["report"]["assumptions"]
    }
    assert version["report"]["lint"][0]["rule"] == "fake-join"


def test_create_project_helper(client: TestClient) -> None:
    assert create_project(client)
