import json

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.container import build_container
from app.infra.seed import DEMO_PROJECT_ID
from app.main import create_app
from tests.llm_helpers import json_transport, ok_chat

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
    requests: list[httpx.Request] = []
    transport = json_transport(
        lambda _request: ok_chat("Процесс начинается с проверки заявления."), requests
    )
    app = create_app(settings, container=build_container(settings, llm_transport=transport))

    with TestClient(app) as configured_client:
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
    request = requests[0]
    assert request.headers["Authorization"] == "Bearer test-only"
    assert str(request.url) == "https://llm.example.test/v1/chat/completions"
    provider_body = json.loads(request.content)
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
    requests: list[httpx.Request] = []
    transport = json_transport(lambda _request: ok_chat("Шаги следуют по порядку."), requests)
    app = create_app(settings, container=build_container(settings, llm_transport=transport))

    with TestClient(app) as configured_client:
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
    provider_body = json.loads(requests[0].content)
    context = provider_body["messages"][1]["content"]
    assert "Сотрудник принимает заявление" in context
    assert "Локальный процесс" in context
