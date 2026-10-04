import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import Settings
from app.container import build_container
from app.infra.seed import DEMO_PROJECT_ID
from app.main import create_app

API = "/api/v1"


def test_assistant_explains_when_provider_is_not_configured(client) -> None:
    response = client.post(
        f"{API}/projects/{DEMO_PROJECT_ID}/assistant",
        json={"message": "Что здесь происходит?", "diagram_xml": "<definitions/>"},
    )

    assert response.status_code == 503
    assert "LLM_PROVIDER" in response.json()["detail"]


def test_assistant_requires_non_empty_message(client) -> None:
    response = client.post(
        f"{API}/projects/{DEMO_PROJECT_ID}/assistant",
        json={"message": "   "},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Введите вопрос помощнику"


def test_configured_assistant_uses_openai_compatible_provider_configuration() -> None:
    settings = Settings(
        mock_delay_scale=0,
        auth_enabled=False,
        llm_provider="openai_compatible",
        llm_api_key="test-only",
        llm_base_url="https://llm.example.test/v1",
        llm_model="approved-model",
    )
    app = create_app(settings, container=build_container(settings))
    response_body = {
        "choices": [{"message": {"content": "Процесс начинается с проверки заявления."}}]
    }

    with (
        TestClient(app) as configured_client,
        patch("app.llm.openai_compatible.urlopen") as urlopen,
    ):
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            response_body
        ).encode()
        response = configured_client.post(
            f"{API}/projects/{DEMO_PROJECT_ID}/assistant",
            json={
                "message": "С чего начинается процесс?",
                "diagram_xml": "<definitions/>",
                "history": [{"role": "user", "text": "Посмотри на схему"}],
            },
        )

    assert response.status_code == 200
    assert response.json() == {"answer": "Процесс начинается с проверки заявления."}
    request = urlopen.call_args.args[0]
    assert request.get_header("Authorization") == "Bearer test-only"
    assert request.full_url == "https://llm.example.test/v1/chat/completions"
    provider_body = json.loads(request.data)
    assert provider_body["model"] == "approved-model"
    context = provider_body["messages"][1]["content"]
    assert "С чего начинается процесс?" in context
    assert "<definitions/>" in context
    assert "Технологическое присоединение" in context


def test_local_draft_chat_sends_its_source_without_persisting_it() -> None:
    settings = Settings(
        mock_delay_scale=0,
        auth_enabled=False,
        llm_provider="deepseek",
        deepseek_api_key="test-only",
    )
    app = create_app(settings, container=build_container(settings))
    response_body = {"choices": [{"message": {"content": "Шаги следуют по порядку."}}]}

    with (
        TestClient(app) as configured_client,
        patch("app.llm.openai_compatible.urlopen") as urlopen,
    ):
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            response_body
        ).encode()
        response = configured_client.post(
            f"{API}/assistant/chat",
            json={
                "project_title": "Локальный процесс",
                "source": "Сотрудник принимает заявление и проверяет документы.",
                "message": "Какие действия выполняются?",
                "diagram_xml": "<definitions/>",
            },
        )

    assert response.status_code == 200
    provider_body = json.loads(urlopen.call_args.args[0].data)
    context = provider_body["messages"][1]["content"]
    assert "Сотрудник принимает заявление" in context
    assert "Локальный процесс" in context
