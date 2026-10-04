"""Общие фикстуры: приложение без задержек mock-а и с засеянными демо-данными."""

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.container import Container, build_container
from app.infra.seed import DEMO_PROJECT_ID
from app.main import create_app

API = "/api/v1"
DEMO = str(DEMO_PROJECT_ID)


@pytest.fixture(autouse=True)
def isolate_external_services(monkeypatch: pytest.MonkeyPatch) -> None:
    """Тесты не наследуют боевые провайдеры, ключи, БД и пути Docker."""
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("STT_PROVIDER", "mock")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)


@pytest.fixture
def settings() -> Settings:
    # API-тесты работают на in-memory репозиториях и не трогают БД разработчика.
    return Settings(
        mock_delay_scale=0,
        database_url=None,
        app_env="test",
        auth_enabled=False,
        rate_limit_enabled=False,
        llm_provider="mock",
        stt_provider="mock",
        deepseek_api_key=None,
        deepgram_api_key=None,
    )


@pytest.fixture
def container(settings: Settings) -> Container:
    return build_container(settings)


@pytest.fixture
def client(settings: Settings, container: Container) -> Iterator[TestClient]:
    with TestClient(create_app(settings, container=container)) as test_client:
        yield test_client


def read_events(
    client: TestClient, run_id: str, **headers: str
) -> list[tuple[str, dict[str, Any]]]:
    """Читает SSE-поток прогона до закрытия (после `done`)."""
    events: list[tuple[str, dict[str, Any]]] = []
    event = ""
    with client.stream("GET", f"{API}/runs/{run_id}/events", headers=headers) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        for line in response.iter_lines():
            if line.startswith("event:"):
                event = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                events.append((event, json.loads(line.removeprefix("data:").strip())))
    return events


def create_project(client: TestClient, title: str = "Тестовый процесс") -> str:
    response = client.post(f"{API}/projects", json={"title": title})
    assert response.status_code == 201
    return response.json()["id"]


def add_text(client: TestClient, project_id: str, content: str, **extra: Any) -> dict[str, Any]:
    response = client.post(
        f"{API}/projects/{project_id}/sources/text", json={"content": content, **extra}
    )
    assert response.status_code == 201, response.text
    return response.json()
