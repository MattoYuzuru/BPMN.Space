"""Вопросы (переходы статусов) и версии схемы (XML, скачивание, ручная правка)."""

from fastapi.testclient import TestClient

from app.fixtures import read_bpmn
from app.infra.seed import seed_id
from tests.conftest import API, DEMO, read_events

MISSING = "00000000-0000-0000-0000-000000000000"


def _question(code: str) -> str:
    return str(seed_id(f"tp861/question/{code[2:]}"))


def test_list_questions_with_filter(client: TestClient) -> None:
    open_questions = client.get(f"{API}/projects/{DEMO}/questions", params={"status": "open"})
    assert [q["code"] for q in open_questions.json()] == ["Q-3", "Q-4", "Q-6"]
    assert client.get(f"{API}/projects/{DEMO}/questions", params={"status": "x"}).status_code == 422
    assert client.get(f"{API}/projects/{MISSING}/questions").status_code == 404


def test_answer_creates_answer_source(client: TestClient) -> None:
    response = client.post(
        f"{API}/questions/{_question('Q-4')}/answer",
        json={"text": "Через 20 рабочих дней заявка аннулируется, заявителю приходит письмо."},
    )
    assert response.status_code == 200
    question = response.json()
    assert question["status"] == "answered"
    source_id = question["answer"]["source_id"]
    sources = {s["id"]: s for s in client.get(f"{API}/projects/{DEMO}").json()["sources"]}
    assert sources[source_id]["kind"] == "answer"
    assert sources[source_id]["question_id"] == question["id"]
    assert sources[source_id]["title"] == "Ответ на Q-4"

    again = client.post(f"{API}/questions/{_question('Q-4')}/answer", json={"text": "Ещё"})
    assert again.status_code == 409
    assert again.json() == {"detail": "Вопрос Q-4 отвечен — ответить на него нельзя"}

    reopened = client.post(f"{API}/questions/{_question('Q-4')}/reopen").json()
    assert reopened["status"] == "open"
    assert reopened["answer"] is None
    sources = {s["id"]: s for s in client.get(f"{API}/projects/{DEMO}").json()["sources"]}
    assert sources[source_id]["active"] is False


def test_ignore_and_reopen(client: TestClient) -> None:
    ignored = client.post(f"{API}/questions/{_question('Q-6')}/ignore")
    assert ignored.json()["status"] == "ignored"
    assert client.post(f"{API}/questions/{_question('Q-6')}/ignore").status_code == 409
    assert client.post(f"{API}/questions/{_question('Q-6')}/reopen").json()["status"] == "open"
    assert client.post(f"{API}/questions/{_question('Q-6')}/reopen").status_code == 409


def test_resolved_question_is_final(client: TestClient) -> None:
    for action in ("ignore", "reopen"):
        response = client.post(f"{API}/questions/{_question('Q-1')}/{action}")
        assert response.status_code == 409
    answer = client.post(f"{API}/questions/{_question('Q-1')}/answer", json={"text": "Ответ"})
    assert answer.status_code == 409


def test_question_errors(client: TestClient) -> None:
    assert client.post(f"{API}/questions/{MISSING}/ignore").status_code == 404
    blank = client.post(f"{API}/questions/{_question('Q-4')}/answer", json={"text": "  "})
    assert blank.status_code == 422
    assert blank.json() == {"detail": "Ответ не может быть пустым"}


def test_unhelpful_answer_returns_question_to_open(client: TestClient) -> None:
    client.post(f"{API}/questions/{_question('Q-6')}/answer", json={"text": "Не знаю"})
    run = client.post(f"{API}/projects/{DEMO}/runs", json={"mode": "analyze"}).json()
    events = read_events(client, run["id"])
    changed = {
        data["question"]["code"]: data["question"] for kind, data in events if kind == "question"
    }
    assert changed["Q-6"]["status"] == "open"
    assert changed["Q-6"]["answer"]["text"] == "Не знаю"
    assert any("Ответ не помог" in warning for warning in events[-1][1]["run"]["warnings"])


def test_versions_list_detail_and_download(client: TestClient) -> None:
    versions = client.get(f"{API}/projects/{DEMO}/versions").json()
    assert [v["number"] for v in versions] == [2, 1]
    assert all("xml" not in v for v in versions)
    v1 = versions[1]
    assert v1["report"]["lint"] == [
        {
            "rule": "fake-join",
            "message": "Входящие потоки не объединены шлюзом",
            "element_id": "Task_CheckCompleteness",
            "severity": "warning",
        }
    ]
    assert versions[0]["diff"] == {"added": 3, "removed": 0, "changed": 2}
    assumptions = {
        (a["element_id"], a["question_id"]) for a in versions[0]["report"]["assumptions"]
    }
    assert ("Gateway_Power", _question("Q-2")) in assumptions

    detail = client.get(f"{API}/versions/{versions[0]['id']}").json()
    assert detail["xml"] == read_bpmn("tp861_v2")

    download = client.get(f"{API}/versions/{versions[0]['id']}/xml")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/xml")
    assert download.headers["content-disposition"].startswith(
        'attachment; filename="diagram-v2.bpmn"'
    )
    assert download.text == detail["xml"]
    assert client.get(f"{API}/versions/{MISSING}").status_code == 404
    assert client.get(f"{API}/versions/{MISSING}/xml").status_code == 404
    assert client.get(f"{API}/projects/{MISSING}/versions").status_code == 404


def test_save_manual_diagram(client: TestClient) -> None:
    xml = read_bpmn("tp861_v2").replace("Провести выездной осмотр", "Осмотреть установку")
    head = client.get(f"{API}/projects/{DEMO}").json()["latest_version"]["id"]
    response = client.put(
        f"{API}/projects/{DEMO}/diagram", json={"xml": xml, "base_version_id": head}
    )
    assert response.status_code == 201
    version = response.json()
    assert version["origin"] == "manual"
    assert version["number"] == 3
    assert version["run_id"] is None
    assert version["diff"] == {"added": 0, "removed": 0, "changed": 1}
    assert version["report"]["xsd_valid"] is True
    assert version["trace"]  # трассировка переносится с прошлой версии

    build = client.post(f"{API}/projects/{DEMO}/runs", json={"mode": "build"}).json()
    events = read_events(client, build["id"])
    rebuilt = next(data["version"] for kind, data in events if kind == "version")
    assert rebuilt["diff"] == {"added": 0, "removed": 0, "changed": 0}  # правка аналитика сохранена


def test_save_manual_diagram_errors(client: TestClient) -> None:
    broken = client.put(
        f"{API}/projects/{DEMO}/diagram",
        json={"xml": "<bpmn:definitions", "base_version_id": None},
    )
    assert broken.status_code == 422
    assert broken.json()["detail"].startswith("XML повреждён")
    not_bpmn = client.put(
        f"{API}/projects/{DEMO}/diagram", json={"xml": "<svg/>", "base_version_id": None}
    )
    assert not_bpmn.json() == {
        "detail": "Это не BPMN 2.0: корневой элемент должен быть bpmn:definitions"
    }
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]>'
        '<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL">&a;</definitions>'
    )
    entity = client.put(
        f"{API}/projects/{DEMO}/diagram", json={"xml": bomb, "base_version_id": None}
    )
    assert entity.status_code == 422
    assert "запрещённые" in entity.json()["detail"]
    blank = client.put(
        f"{API}/projects/{DEMO}/diagram", json={"xml": "   ", "base_version_id": None}
    )
    assert blank.json() == {"detail": "Схема пустая"}
    missing = client.put(
        f"{API}/projects/{MISSING}/diagram", json={"xml": "<a/>", "base_version_id": None}
    )
    assert missing.status_code == 404


def test_identical_diagram_save_does_not_create_version(client: TestClient) -> None:
    versions = client.get(f"{API}/projects/{DEMO}/versions").json()
    head = versions[0]
    xml = client.get(f"{API}/versions/{head['id']}").json()["xml"]
    for _ in range(3):
        response = client.put(
            f"{API}/projects/{DEMO}/diagram", json={"xml": xml, "base_version_id": head["id"]}
        )
        assert response.status_code == 201
        assert response.json() == head
    assert client.get(f"{API}/projects/{DEMO}/versions").json() == versions
    stale = client.put(
        f"{API}/projects/{DEMO}/diagram", json={"xml": xml, "base_version_id": versions[1]["id"]}
    )
    assert stale.status_code == 409
