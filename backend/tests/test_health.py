from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


def test_health() -> None:
    assert TestClient(app).get("/health").json() == {"status": "ok"}


def test_settings_defaults() -> None:
    assert get_settings().api_prefix == "/api/v1"
