"""Ключи моделей по HTTP: список без секретов, проверка у провайдера, права и выбор модели."""

import json
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.container import Container, build_container
from app.domain.models import RunMode
from app.infra.seed import DEMO_PROJECT_ID
from app.llm.base import PipelineError
from app.llm.client import redact_secrets
from app.main import create_app
from app.services.auth import optional_user
from app.services.errors import InvalidInputError, NotFoundError, UnavailableError
from app.services.runs import _RunState
from tests.llm_helpers import json_transport, ok_chat

API = "/api/v1"
KEY_A = "sk-ant-api03-ALICE-SECRET-0001"
KEY_B = "sk-proj-BOB-SECRET-0002"
_NO_HASH: Any = SimpleNamespace(source_snapshot_hash=None)
ALICE = SimpleNamespace(id=uuid4(), email="alice@example.com")
BOB = SimpleNamespace(id=uuid4(), email="bob@example.com")


class Stack:
    def __init__(self, settings: Settings) -> None:
        self.requests: list[httpx.Request] = []
        self.valid_keys = {KEY_A, KEY_B}
        self.user: Any = ALICE
        self.container: Container = build_container(
            settings, llm_transport=json_transport(self._provider, self.requests)
        )
        self.app = create_app(settings, container=self.container)
        self.app.dependency_overrides[optional_user] = lambda: self.user

    def _provider(self, request: httpx.Request) -> httpx.Response:
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if token not in self.valid_keys:
            return httpx.Response(401, text="invalid")
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "gpt-4o"}, {"id": "o3"}]})
        return ok_chat("Ответ помощника")


def _settings(**extra: Any) -> Settings:
    values: dict[str, Any] = {
        "mock_delay_scale": 0,
        "auth_enabled": False,
        "seed_demo_data": True,
        "credentials_encryption_key": SecretStr(Fernet.generate_key().decode()),
        "rate_limit_enabled": False,
        "llm_models_cache_sec": 300,
    }
    values.update(extra)
    return Settings(**values)


@pytest.fixture
def stack() -> Iterator[Stack]:
    s = Stack(_settings())
    with TestClient(s.app):
        yield s


def _call(stack: Stack, method: str, path: str, **kw: Any) -> Any:
    with TestClient(stack.app) as client:
        return client.request(method, f"{API}{path}", **kw)


def _create(stack: Stack, key: str = KEY_B, **extra: Any) -> dict[str, Any]:
    body = {"provider": "openai", "api_key": key, **extra}
    response = _call(stack, "post", "/me/llm-credentials", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_validates_hides_the_key_and_picks_first_as_default(stack: Stack) -> None:
    stack.user = BOB
    created = _create(stack, label="Рабочий")
    assert created["label"] == "Рабочий"
    assert created["key_hint"] == KEY_B[-4:]
    assert created["is_default"] is True
    assert created["default_model"] == "gpt-4o"
    assert created["provider"] == "openai"
    assert KEY_B not in json.dumps(created)
    # провайдеру ушёл запрос списка моделей с этим ключом
    assert stack.requests[0].headers["Authorization"] == f"Bearer {KEY_B}"
    listing = _call(stack, "get", "/me/llm-credentials")
    assert listing.json()["storage_available"] is True
    assert [item["id"] for item in listing.json()["items"]] == [created["id"]]
    assert KEY_B not in listing.text


def test_key_is_stored_encrypted_and_never_leaves_the_server(stack: Stack) -> None:
    stack.user = BOB
    created = _create(stack)
    repo = stack.container.repos.llm_credentials
    assert repo is not None
    stored = stack.container.repos.llm_credentials._items[UUID(created["id"])]  # type: ignore[attr-defined]
    assert KEY_B.encode() not in stored.encrypted_key
    assert KEY_B not in repr(stored)
    for response in (
        _call(stack, "get", f"/me/llm-credentials/{created['id']}/models"),
        _call(stack, "patch", f"/me/llm-credentials/{created['id']}", json={"label": "Новый"}),
    ):
        assert KEY_B not in response.text


def test_invalid_key_is_rejected_and_nothing_is_stored(stack: Stack) -> None:
    stack.user = BOB
    response = _call(
        stack,
        "post",
        "/me/llm-credentials",
        json={"provider": "openai", "api_key": "sk-wrong-key-123"},
    )
    assert response.status_code == 422
    assert "ключ" in response.json()["detail"]
    assert "sk-wrong-key-123" not in response.text
    assert _call(stack, "get", "/me/llm-credentials").json()["items"] == []


@pytest.mark.parametrize(
    "base_url",
    [
        "http://api.example.com/v1",
        "https://127.0.0.1:8000/v1",
        "https://169.254.169.254/latest",
        "https://[::1]/v1",
        "https://" + "user" + ":" + "x" + "@api.example.com/v1",
        None,
    ],
)
def test_compatible_provider_base_url_is_validated(stack: Stack, base_url: str | None) -> None:
    stack.user = BOB
    body = {"provider": "openai_compatible", "api_key": KEY_B, "base_url": base_url}
    response = _call(stack, "post", "/me/llm-credentials", json=body)
    assert response.status_code == 422, response.text
    assert stack.requests == []  # до проверки адреса запрос наружу не уходит


def test_fixed_provider_ignores_a_user_base_url(stack: Stack) -> None:
    stack.user = BOB
    created = _create(stack, base_url="https://evil.example/v1")
    assert created["base_url"] is None
    assert str(stack.requests[0].url).startswith("https://api.openai.com/")


def test_other_users_cannot_see_or_touch_a_credential(stack: Stack) -> None:
    stack.user = BOB
    created = _create(stack)
    stack.user = ALICE
    assert _call(stack, "get", "/me/llm-credentials").json()["items"] == []
    for method, path, kw in [
        ("patch", f"/me/llm-credentials/{created['id']}", {"json": {"label": "x"}}),
        ("delete", f"/me/llm-credentials/{created['id']}", {}),
        ("get", f"/me/llm-credentials/{created['id']}/models", {}),
    ]:
        assert _call(stack, method, path, **kw).status_code == 404


def test_guest_gets_401(stack: Stack) -> None:
    stack.user = None
    assert _call(stack, "get", "/me/llm-credentials").status_code == 401


def test_update_default_switches_and_delete_removes(stack: Stack) -> None:
    stack.user = BOB
    first = _create(stack, label="Первый")
    second = _create(stack, label="Второй", is_default=True)
    items = _call(stack, "get", "/me/llm-credentials").json()["items"]
    assert [i["id"] for i in items] == [second["id"], first["id"]]
    assert [i["is_default"] for i in items] == [True, False]
    updated = _call(
        stack,
        "patch",
        f"/me/llm-credentials/{first['id']}",
        json={"is_default": True, "default_model": "o3"},
    ).json()
    assert updated["is_default"] is True
    assert updated["default_model"] == "o3"
    after = _call(stack, "get", "/me/llm-credentials").json()["items"]
    assert [i["is_default"] for i in after] == [True, False]
    assert _call(stack, "delete", f"/me/llm-credentials/{first['id']}").status_code == 204
    assert len(_call(stack, "get", "/me/llm-credentials").json()["items"]) == 1
    assert _call(stack, "get", f"/me/llm-credentials/{first['id']}/models").status_code == 404


def test_models_are_cached_between_requests(stack: Stack) -> None:
    stack.user = BOB
    created = _create(stack)
    before = len(stack.requests)
    responses = [
        _call(stack, "get", f"/me/llm-credentials/{created['id']}/models").json() for _ in range(3)
    ]
    models = responses[-1]
    assert [m["id"] for m in models["items"]] == ["gpt-4o", "o3"]
    assert len(stack.requests) == before  # список запомнен при создании


def test_models_failure_is_recorded_without_the_key(stack: Stack) -> None:
    stack.user = BOB
    created = _create(stack)
    stack.valid_keys.clear()
    stack.container.llm_credentials._models.clear()
    response = _call(stack, "get", f"/me/llm-credentials/{created['id']}/models")
    assert response.status_code == 422
    item = _call(stack, "get", "/me/llm-credentials").json()["items"][0]
    assert item["last_error"]
    assert KEY_B not in json.dumps(item)


def test_storage_is_refused_in_production_without_encryption_key() -> None:
    s = Stack(
        _settings(
            app_env="production",
            bpmn_tools_url="http://127.0.0.1:1",
            credentials_encryption_key=None,
            llm_provider="openai_compatible",
            llm_api_key=SecretStr("server-key-1234"),
            llm_base_url="https://llm.example.test/v1",
            llm_model="m",
            stt_provider="deepgram",
            deepgram_api_key=SecretStr("x"),
        )
    )
    s.user = BOB
    listing = _call(s, "get", "/me/llm-credentials")
    assert listing.json()["storage_available"] is False
    response = _call(
        s, "post", "/me/llm-credentials", json={"provider": "openai", "api_key": KEY_B}
    )
    assert response.status_code == 503
    assert s.requests == []


def test_production_refuses_mock_stt_and_mock_llm_without_user_keys() -> None:
    with pytest.raises(ValueError, match="STT_PROVIDER=mock"):
        build_container(Settings(app_env="production", llm_provider="mock"))
    with pytest.raises(ValueError, match="CREDENTIALS_ENCRYPTION_KEY"):
        build_container(
            Settings(
                app_env="production",
                stt_provider="deepgram",
                deepgram_api_key=SecretStr("x"),
                llm_provider="mock",
            )
        )


def test_production_does_not_seed_demo_data_by_default() -> None:
    assert Settings(app_env="production").seed_demo_data is False
    assert Settings(app_env="dev").seed_demo_data is True
    assert Settings(app_env="production", seed_demo_data=True).seed_demo_data is True


# ---------- выбор модели ----------


async def _resolve(stack: Stack, user: Any, **kw: Any):
    return await stack.container.runs._resolver.resolve(user.id if user else None, **kw)


async def test_resolution_order_explicit_then_default_then_server_then_mock(stack: Stack) -> None:
    stack.user = BOB
    first = _create(stack, label="Первый", default_model="gpt-4o")
    second = _create(stack, label="Второй", default_model="o3", is_default=True)
    default = await _resolve(stack, BOB)
    assert (default.provider, default.model, str(default.credential_id)) == (
        "openai",
        "o3",
        second["id"],
    )
    explicit = await _resolve(stack, BOB, credential_id=UUID(first["id"]), model="gpt-4.1")
    assert (explicit.model, str(explicit.credential_id)) == ("gpt-4.1", first["id"])
    await explicit.release()
    # нет ключа — сервер (здесь mock)
    nobody = await _resolve(stack, ALICE)
    assert (nobody.provider, nobody.source, nobody.credential_id) == ("mock", "mock", None)
    guest = await _resolve(stack, None)
    assert guest.source == "mock"


async def test_foreign_credential_is_not_found_and_model_needs_a_key(stack: Stack) -> None:
    stack.user = BOB
    created = _create(stack)
    with pytest.raises(NotFoundError):
        await _resolve(stack, ALICE, credential_id=UUID(created["id"]))
    with pytest.raises(NotFoundError):
        await _resolve(stack, None, credential_id=UUID(created["id"]))
    with pytest.raises(InvalidInputError, match="вместе с ключом"):
        await _resolve(stack, ALICE, model="gpt-4o")


async def test_user_without_model_for_key_gets_a_clear_error(stack: Stack) -> None:
    stack.user = BOB
    created = _create(stack)
    stack.container.repos.llm_credentials._items[UUID(created["id"])].default_model = None  # type: ignore[attr-defined]
    with pytest.raises(InvalidInputError, match="Выберите модель"):
        await _resolve(stack, BOB)


async def test_production_without_any_key_asks_to_add_one() -> None:
    s = Stack(
        _settings(
            app_env="production",
            bpmn_tools_url="http://127.0.0.1:1",
            stt_provider="deepgram",
            deepgram_api_key=SecretStr("x"),
            llm_provider="mock",
        )
    )
    with pytest.raises(InvalidInputError, match="Добавьте ключ модели"):
        await _resolve(s, ALICE)
    with pytest.raises(UnavailableError, match="Добавьте ключ модели"):
        await s.container.runs._resolver.resolve(ALICE.id, allow_mock=False)


def test_run_records_provider_model_and_credential_but_not_the_key(stack: Stack) -> None:
    stack.user = BOB
    created = _create(stack, default_model="gpt-4o")
    with TestClient(stack.app) as client:
        started = client.post(
            f"{API}/projects/{DEMO_PROJECT_ID}/runs",
            json={"mode": RunMode.ANALYZE.value, "credential_id": created["id"], "model": "o3"},
        )
        assert started.status_code == 202, started.text
        body = started.json()
        assert (body["provider"], body["model"], body["credential_id"]) == (
            "openai",
            "o3",
            created["id"],
        )
        assert KEY_B not in started.text
        stored = stack.container.repos.runs  # type: ignore[attr-defined]
        run = client.get(f"{API}/runs/{body['id']}").json()
        assert run["model"] == "o3"
        assert KEY_B not in json.dumps(run)
        saved = stack.container.repos.runs._items[UUID(body["id"])]  # type: ignore[attr-defined]
        assert KEY_B not in json.dumps(saved.ir, default=str)
        assert stored is not None


def test_run_with_foreign_credential_is_404(stack: Stack) -> None:
    stack.user = BOB
    created = _create(stack)
    stack.user = ALICE
    with TestClient(stack.app) as client:
        response = client.post(
            f"{API}/projects/{DEMO_PROJECT_ID}/runs",
            json={"mode": "analyze", "credential_id": created["id"]},
        )
    assert response.status_code == 404


def test_assistant_uses_the_callers_own_key(stack: Stack) -> None:
    stack.user = BOB
    _create(stack, default_model="gpt-4o")
    stack.user = ALICE
    other = _create_for(stack, ALICE, KEY_A)
    assert other["provider"] == "openai"
    stack.requests.clear()
    stack.user = BOB
    response = _call(
        stack,
        "post",
        f"/projects/{DEMO_PROJECT_ID}/assistant",
        json={"message": "Что здесь?", "diagram_xml": "<definitions/>"},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"answer": "Ответ помощника"}
    chat = next(r for r in stack.requests if r.method == "POST")
    assert chat.headers["Authorization"] == f"Bearer {KEY_B}"
    assert json.loads(chat.content)["model"] == "gpt-4o"
    stack.requests.clear()
    stack.user = ALICE
    _call(
        stack,
        "post",
        f"/projects/{DEMO_PROJECT_ID}/assistant",
        json={"message": "Что здесь?", "diagram_xml": "<definitions/>"},
    )
    chat = next(r for r in stack.requests if r.method == "POST")
    assert chat.headers["Authorization"] == f"Bearer {KEY_A}"


def _create_for(stack: Stack, user: Any, key: str) -> dict[str, Any]:
    stack.user = user
    return _create(stack, key)


def test_assistant_without_any_key_explains_how_to_connect(stack: Stack) -> None:
    stack.user = ALICE
    response = _call(
        stack,
        "post",
        f"/projects/{DEMO_PROJECT_ID}/assistant",
        json={"message": "Что здесь?", "diagram_xml": "<definitions/>"},
    )
    assert response.status_code == 503
    assert "LLM_PROVIDER" in response.json()["detail"]


# ---------- восстановление прогона после рестарта ----------


async def test_recovery_restores_provider_model_and_rejects_a_deleted_key(stack: Stack) -> None:
    stack.user = BOB
    created = _create(stack, default_model="gpt-4o")
    runs = stack.container.runs
    run = await runs.start(
        DEMO_PROJECT_ID, mode=RunMode.ANALYZE, created_by=BOB.id, credential_id=UUID(created["id"])
    )
    await stack.container.spawner.wait_idle()
    run = await runs.get(run.id)
    assert (run.ir or {})["execution"]["provider"] == "openai"
    # «после рестарта»: пайплайн в памяти потерян, ключ берётся по записанному credential_id
    restored = await runs._run_pipeline(run)
    assert (restored.provider, restored.model) == ("openai", "gpt-4o")
    await restored.release()
    assert _call(stack, "delete", f"/me/llm-credentials/{created['id']}").status_code == 204
    with pytest.raises(PipelineError, match="восстановить модель"):
        await runs._run_pipeline(run)


async def test_recovery_rejects_changed_model_or_provider(stack: Stack) -> None:
    runs = stack.container.runs
    run = await runs.start(DEMO_PROJECT_ID, mode=RunMode.ANALYZE, created_by=None)
    await stack.container.spawner.wait_idle()
    run = await runs.get(run.id)
    state = _RunState(pipeline=stack.container.runs._pipeline)
    execution = dict((run.ir or {})["execution"])
    execution.pop("source_snapshot_hash", None)
    run.model = "другая-модель"
    with pytest.raises(PipelineError, match="Модель изменилась"):
        runs._check_recovered_input(run, _NO_HASH, execution, state)
    assert state.pipeline is not None
    run.model = state.pipeline.model_name
    execution["provider"] = "anthropic"
    with pytest.raises(PipelineError, match="Провайдер"):
        runs._check_recovered_input(run, _NO_HASH, execution, state)


def test_error_text_never_contains_the_key(stack: Stack) -> None:
    assert KEY_A not in redact_secrets(f"boom {KEY_A}")
