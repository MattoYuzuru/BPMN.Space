"""Источники: текст и голос, файлы всех форматов, правка, выключение, удаление; расшифровка."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.container import Container
from app.infra.seed import seed_id
from tests.conftest import API, DEMO, add_text, create_project

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
MISSING = "00000000-0000-0000-0000-000000000000"


def _upload(
    client: TestClient, project_id: str, name: str, data: bytes, mime: str = "text/plain"
) -> tuple[int, dict[str, object]]:
    response = client.post(
        f"{API}/projects/{project_id}/sources/file", files={"file": (name, data, mime)}
    )
    return response.status_code, response.json()


def test_text_and_voice_sources(client: TestClient) -> None:
    project_id = create_project(client)
    text = add_text(client, project_id, "# Регламент\nОператор принимает заявку.")
    assert text["kind"] == "text"
    assert text["title"] == "Регламент"
    assert text["status"] == "ready"
    assert text["active"] is True

    voice = add_text(
        client, project_id, "Заявку смотрит дежурный инженер.", kind="voice", duration_sec=75
    )
    assert voice["kind"] == "voice"
    assert voice["title"] == "Голосовая заметка, 1:15"
    assert voice["duration_sec"] == 75

    project = client.get(f"{API}/projects/{project_id}").json()
    assert project["status"] == "ready"
    assert project["counts"]["sources"] == 2


def test_text_source_validation(client: TestClient) -> None:
    project_id = create_project(client)
    blank = client.post(f"{API}/projects/{project_id}/sources/text", json={"content": "   "})
    assert blank.status_code == 422
    assert blank.json() == {"detail": "Текст источника не может быть пустым"}
    answer = client.post(
        f"{API}/projects/{project_id}/sources/text", json={"content": "x", "kind": "answer"}
    )
    assert answer.status_code == 422
    missing = client.post(f"{API}/projects/{MISSING}/sources/text", json={"content": "x"})
    assert missing.status_code == 404


def test_markdown_file_is_ready_immediately(client: TestClient) -> None:
    project_id = create_project(client)
    status, source = _upload(client, project_id, "регламент.md", "# Шаги\nТекст".encode())
    assert status == 201
    assert source["status"] == "ready"
    assert source["content"] == "# Шаги\nТекст"
    assert source["file_name"] == "регламент.md"
    assert source["size_bytes"] == len("# Шаги\nТекст".encode())

    status, cp1251 = _upload(client, project_id, "old.txt", "Проверка".encode("cp1251"))
    assert status == 201
    assert cp1251["content"] == "Проверка"


def test_csv_file_is_parsed_and_saved_as_a_regular_source(client: TestClient) -> None:
    project_id = create_project(client)
    data = 'Роль;Ответственность\n"Клиент";"Подаёт заявку; прикладывает документы"\n'.encode()
    status, source = _upload(client, project_id, "roles.csv", data, "text/csv")

    assert status == 201
    assert source["kind"] == "file"
    assert source["status"] == "ready"
    content = str(source["content"])
    assert content.startswith("CSV-таблица.")
    assert 'Строка 2: ["Клиент", "Подаёт заявку; прикладывает документы"]' in content
    detail = client.get(f"{API}/projects/{project_id}").json()
    assert detail["sources"][0]["content"] == source["content"]


def test_parsed_file_over_text_limit_fails_instead_of_silently_truncating(
    client: TestClient, container: Container
) -> None:
    project_id = create_project(client)
    container.sources._max_text = 60
    status, source = _upload(client, project_id, "large.csv", b"a,b\n" + b"x,y\n" * 10, "text/csv")

    assert status == 201
    assert source["status"] == "failed"
    assert "превышает лимит 60 символов" in str(source["error"])


def test_docx_from_examples_is_parsed_in_background(client: TestClient) -> None:
    project_id = create_project(client)
    data = (EXAMPLES / "tp861" / "input" / "project-finances.docx").read_bytes()
    status, source = _upload(
        client,
        project_id,
        "Финансы проекта.docx",
        data,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert status == 201
    assert source["status"] == "processing"
    detail = client.get(f"{API}/projects/{project_id}").json()
    parsed = detail["sources"][0]
    assert parsed["status"] == "ready"
    assert "финансовый отдел сетевой организации" in parsed["content"]


def test_pdf_and_broken_docx(client: TestClient) -> None:
    project_id = create_project(client)
    _upload(client, project_id, "Приказ.pdf", b"%PDF-1.7 demo", "application/pdf")
    _upload(client, project_id, "broken.docx", b"not a zip", "application/octet-stream")
    sources = {
        s["file_name"]: s for s in client.get(f"{API}/projects/{project_id}").json()["sources"]
    }
    assert sources["Приказ.pdf"]["status"] == "failed"
    assert "Не удалось прочитать PDF" in sources["Приказ.pdf"]["error"]
    assert sources["broken.docx"]["status"] == "failed"
    assert sources["broken.docx"]["error"] == "Не удалось прочитать .docx: файл повреждён"


def test_file_upload_errors(client: TestClient, container: Container) -> None:
    project_id = create_project(client)
    status, body = _upload(client, project_id, "схема.xlsx", b"data")
    assert status == 415
    assert "Формат не поддерживается" in str(body["detail"])
    status, body = _upload(client, project_id, "пустой.txt", b"")
    assert (status, body) == (422, {"detail": "Файл пустой"})
    status, body = _upload(client, project_id, "nobody.txt", b"\x00\xff\xfe")
    assert status == 201  # cp1251 декодирует любые байты; пустым не считается
    container.sources._max_upload = 4
    status, body = _upload(client, project_id, "big.txt", b"12345")
    assert status == 413
    assert body == {"detail": "Файл больше 1 МБ"}


def test_update_and_toggle_source(client: TestClient) -> None:
    project_id = create_project(client)
    source = add_text(client, project_id, "Первый вариант")
    patched = client.patch(
        f"{API}/sources/{source['id']}", json={"content": "Второй вариант", "title": "Заметка"}
    ).json()
    assert patched["content"] == "Второй вариант"
    assert patched["title"] == "Заметка"
    off = client.patch(f"{API}/sources/{source['id']}", json={"active": False}).json()
    assert off["active"] is False
    assert client.get(f"{API}/projects/{project_id}").json()["status"] == "empty"
    run = client.post(f"{API}/projects/{project_id}/runs", json={"mode": "analyze"})
    assert run.status_code == 409
    empty = client.patch(f"{API}/sources/{source['id']}", json={"content": ""})
    assert empty.status_code == 422
    assert client.patch(f"{API}/sources/{MISSING}", json={"active": True}).status_code == 404


def test_failed_source_becomes_ready_after_manual_text(client: TestClient) -> None:
    project_id = create_project(client)
    _, source = _upload(client, project_id, "broken.docx", b"zip?", "application/octet-stream")
    fixed = client.patch(f"{API}/sources/{source['id']}", json={"content": "Текст вручную"})
    assert fixed.json()["status"] == "ready"
    assert fixed.json()["error"] is None


def test_editing_and_deleting_answer_source_updates_question(client: TestClient) -> None:
    answer_id = str(seed_id("tp861/source/answer/Q-5"))
    client.patch(f"{API}/sources/{answer_id}", json={"content": "Новый текст ответа"})
    questions = {q["code"]: q for q in client.get(f"{API}/projects/{DEMO}/questions").json()}
    assert questions["Q-5"]["answer"]["text"] == "Новый текст ответа"

    assert client.delete(f"{API}/sources/{answer_id}").status_code == 204
    questions = {q["code"]: q for q in client.get(f"{API}/projects/{DEMO}/questions").json()}
    assert questions["Q-5"]["status"] == "open"
    assert questions["Q-5"]["answer"] is None
    assert client.delete(f"{API}/sources/{answer_id}").status_code == 404


def test_delete_file_source(client: TestClient) -> None:
    project_id = create_project(client)
    _, source = _upload(client, project_id, "a.txt", b"text")
    assert client.delete(f"{API}/sources/{source['id']}").status_code == 204
    assert client.get(f"{API}/projects/{project_id}").json()["sources"] == []


def test_transcription(client: TestClient) -> None:
    audio = b"\x1aE\xdf\xa3" + b"\x00" * 12_000
    response = client.post(
        f"{API}/transcriptions", files={"file": ("note.webm", audio, "audio/webm;codecs=opus")}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["language"] == "ru-RU"
    assert body["duration_sec"] == 3.0
    assert len(body["text"]) > 50

    wrong = client.post(f"{API}/transcriptions", files={"file": ("a.png", b"x", "image/png")})
    assert wrong.status_code == 415
    empty = client.post(f"{API}/transcriptions", files={"file": ("a.ogg", b"", "audio/ogg")})
    assert empty.status_code == 422
    assert client.post(f"{API}/transcriptions").status_code == 422
