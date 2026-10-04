import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.auth import UserCreate
from app.config import Settings
from app.container import build_container
from app.main import create_app
from app.services.access import token_digest


def test_registration_schema_does_not_expose_server_managed_flags() -> None:
    schema = UserCreate.model_json_schema()

    assert set(schema["properties"]) == {"email", "password"}


@pytest.mark.parametrize("field", ["is_active", "is_superuser", "is_verified"])
def test_registration_rejects_server_managed_flags(field: str) -> None:
    with pytest.raises(ValidationError):
        UserCreate.model_validate(
            {"email": "person@example.com", "password": "very-long-test-password", field: True}
        )


def test_share_token_is_stored_as_a_one_way_digest() -> None:
    sample = "sample-share-token-value"

    assert token_digest(sample) != sample
    assert token_digest(sample) == token_digest(sample)


def test_cookie_mutations_require_a_double_submit_csrf_token() -> None:
    settings = Settings(auth_enabled=True, database_url=None, seed_demo_data=False)
    app = create_app(settings, container=build_container(settings))

    with TestClient(app) as client:
        response = client.post("/api/v1/projects", json={"title": "Private"})
        assert response.status_code == 403

        csrf = client.get("/api/v1/auth/csrf")
        assert csrf.status_code == 200
        token = csrf.json()["csrf_token"]
        assert client.cookies.get("arkhitektor_csrf") == token

        response = client.post(
            "/api/v1/projects",
            json={"title": "Private"},
            headers={"x-csrf-token": token},
        )
        # Без БД приложение не может разрешить FastAPI Users' database dependency.
        assert response.status_code == 503


def test_authentication_and_sharing_are_in_openapi() -> None:
    settings = Settings(auth_enabled=True, database_url=None, seed_demo_data=False)
    app = create_app(settings, container=build_container(settings))
    paths = app.openapi()["paths"]

    assert "/api/v1/auth/register" in paths
    assert "/api/v1/auth/session/login" in paths
    assert "/api/v1/projects/{project_id}/share-links" in paths
    assert "/api/v1/shares/{token}/accept" in paths
