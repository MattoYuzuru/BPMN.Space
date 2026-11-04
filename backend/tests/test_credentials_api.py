"""Ключи по типам задач по HTTP (RFC-0006): карточки возможностей, проверка, права, совместимость.

In-memory стенд с подменённым HTTP провайдеров: Deepgram и OpenAI-совместимые сервисы отвечают
записанными ответами. Проверяется, что ключ принимается один раз, не возвращается и что отказ
провайдера виден пользователю понятным текстом, а не телом ответа.
"""

import asyncio
import json
from collections.abc import Iterator
from datetime import UTC, datetime
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
from app.domain.capabilities import CredentialKind
from app.domain.credentials import Credential
from app.main import create_app
from app.services.auth import optional_user
from tests.llm_helpers import json_transport

API = "/api/v1"
DEEPGRAM_KEY = "dg-user-secret-key-0001"
OPENAI_KEY = "sk-user-secret-key-0002"
ALICE = SimpleNamespace(id=uuid4(), email="alice@example.com")


class Stack:
    """Контейнер с записанными ответами провайдеров инструментов и моделей."""

    def __init__(self, settings: Settings) -> None:
        self.requests: list[httpx.Request] = []
        self.valid_keys = {DEEPGRAM_KEY, OPENAI_KEY}
        self.user: Any = ALICE
        self.container: Container = build_container(
            settings,
            llm_transport=json_transport(self._llm_provider, self.requests),
            adapter_transport=httpx.MockTransport(self._adapter_provider),
        )
        self.app = create_app(settings, container=self.container)
        self.app.dependency_overrides[optional_user] = lambda: self.user

    def _llm_provider(self, request: httpx.Request) -> httpx.Response:
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if token not in self.valid_keys:
            return httpx.Response(401, text="invalid")
        return httpx.Response(200, json={"data": [{"id": "gpt-4o"}]})

    def _adapter_provider(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        token = request.headers.get("Authorization", "")
        key = token.removeprefix("Token ").removeprefix("Bearer ")
        if request.url.path.endswith("/v1/auth/token"):
            return (
                httpx.Response(200, json={"access_token": "x"})
                if DEEPGRAM_KEY in self.valid_keys and key == DEEPGRAM_KEY
                else httpx.Response(401, text="invalid")
            )
        if request.url.path.endswith("/models"):
            if key not in self.valid_keys:
                return httpx.Response(401, text="invalid")
            return httpx.Response(200, json={"data": [{"id": "whisper-1"}]})
        if request.url.path.endswith("/audio/transcriptions"):
            return httpx.Response(200, json={"text": "Проверить заявку", "duration": 3.5})
        return httpx.Response(404, text="not found")


def _settings(**extra: Any) -> Settings:
    values: dict[str, Any] = {
        "mock_delay_scale": 0,
        "auth_enabled": False,
        "seed_demo_data": True,
        "credentials_encryption_key": SecretStr(Fernet.generate_key().decode()),
        "rate_limit_enabled": False,
        "capability_retry_base_sec": 0,
        "capability_retry_max_sec": 0,
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


def _create(stack: Stack, **body: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kinds": ["speech_to_text"],
        "provider": "deepgram",
        "api_key": DEEPGRAM_KEY,
        **body,
    }
    response = _call(stack, "post", "/me/credentials", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_capability_cards_have_providers_and_no_keys_yet(stack: Stack) -> None:
    listing = _call(stack, "get", "/me/credentials")
    assert listing.status_code == 200
    body = listing.json()
    assert body["items"] == []
    assert body["storage_available"] is True
    cards = {card["capability"]: card for card in body["capabilities"]}
    assert set(cards) == {
        "llm",
        "speech_to_text",
        "ocr",
        "vision",
        "video_understanding",
        "web_search",
        "web_fetch",
        "tts",
    }
    stt = cards["speech_to_text"]
    assert [provider["id"] for provider in stt["providers"]] == [
        "deepgram",
        "openai",
        "groq",
        "openai_compatible",
    ]
    assert stt["keys"] == 0
    assert stt["available"] is False
    assert cards["vision"]["providers"] == []  # волна 3: провайдеры ещё не подключены
    assert all(card["tool"] for card in body["capabilities"])


def test_create_stt_key_checks_provider_and_never_returns_secret(stack: Stack) -> None:
    created = _create(stack, label="Мой Deepgram")
    assert created["provider"] == "deepgram"
    assert created["kinds"] == ["speech_to_text"]
    assert created["key_hint"] == DEEPGRAM_KEY[-4:]
    assert created["capabilities"] == ["speech_to_text"]
    assert created["priority"] == 100
    assert created["enabled"] is True
    assert created["is_default"] is False
    assert DEEPGRAM_KEY not in json.dumps(created)
    assert any(
        request.url.path == "/v1/auth/token" for request in stack.requests
    )  # ключ проверен дешёвым запросом

    stored = stack.container.repos.credentials._items[UUID(created["id"])]  # type: ignore[union-attr]
    assert DEEPGRAM_KEY.encode() not in stored.encrypted_key

    listing = _call(stack, "get", "/me/credentials").json()
    assert listing["items"][0]["id"] == created["id"]
    card = next(c for c in listing["capabilities"] if c["capability"] == "speech_to_text")
    assert card["keys"] == 1
    assert card["available"] is True


def test_create_rejects_provider_that_cannot_do_capability(stack: Stack) -> None:
    response = _call(
        stack,
        "post",
        "/me/credentials",
        json={
            "kinds": ["speech_to_text"],
            "provider": "anthropic",
            "api_key": OPENAI_KEY,
        },
    )
    assert response.status_code == 422
    assert "не умеет" in response.json()["detail"]
    assert _call(stack, "get", "/me/credentials").json()["items"] == []


def test_create_rejects_invalid_key_without_leaking_provider_text(stack: Stack) -> None:
    stack.valid_keys.discard(DEEPGRAM_KEY)
    response = _call(
        stack,
        "post",
        "/me/credentials",
        json={
            "kinds": ["speech_to_text"],
            "provider": "deepgram",
            "api_key": DEEPGRAM_KEY,
        },
    )
    assert response.status_code == 422
    assert "отклонил" in response.json()["detail"]
    assert DEEPGRAM_KEY not in response.text
    assert _call(stack, "get", "/me/credentials").json()["items"] == []


def test_stt_compatible_url_is_checked_before_saving(stack: Stack) -> None:
    """Совместимому распознаванию нужен адрес, и он проходит те же запреты, что LLM (ADR-0011)."""
    missing = _call(
        stack,
        "post",
        "/me/credentials",
        json={
            "kinds": ["speech_to_text"],
            "provider": "openai_compatible",
            "api_key": OPENAI_KEY,
        },
    )
    assert missing.status_code == 422
    assert "адрес API" in missing.json()["detail"]
    insecure = _call(
        stack,
        "post",
        "/me/credentials",
        json={
            "kinds": ["speech_to_text"],
            "provider": "openai_compatible",
            "api_key": OPENAI_KEY,
            "base_url": "https://" + "user" + ":" + "secret" + "@stt.example.com/v1",
        },
    )
    assert insecure.status_code == 422
    assert "логин" in insecure.json()["detail"]
    assert OPENAI_KEY not in insecure.text
    assert _call(stack, "get", "/me/credentials").json()["items"] == []


def test_llm_key_with_several_kinds_appears_in_both_apis(stack: Stack) -> None:
    created = _create(
        stack,
        kinds=["llm", "speech_to_text"],
        provider="openai",
        api_key=OPENAI_KEY,
        label="OpenAI общий",
    )
    assert set(created["capabilities"]) == {"llm", "speech_to_text"}
    # Ключ модели: виден в старой ручке и не теряет модель по умолчанию.
    old = _call(stack, "get", "/me/llm-credentials").json()
    assert [item["id"] for item in old["items"]] == [created["id"]]
    assert old["items"][0]["default_model"] == "gpt-4o"
    assert old["items"][0]["is_default"] is True
    models = _call(stack, "get", f"/me/llm-credentials/{created['id']}/models")
    assert models.status_code == 200
    assert models.json()["items"][0]["id"] == "gpt-4o"
    # Ключ без типа llm в список моделей не попадает.
    _create(stack, label="Только речь")
    llm_ids = [item["id"] for item in _call(stack, "get", "/me/llm-credentials").json()["items"]]
    assert created["id"] in llm_ids
    assert len(llm_ids) == 1


def test_legacy_llm_endpoint_creates_key_for_generic_list(stack: Stack) -> None:
    response = _call(
        stack,
        "post",
        "/me/llm-credentials",
        json={"provider": "openai", "api_key": OPENAI_KEY},
    )
    assert response.status_code == 201, response.text
    generic = _call(stack, "get", "/me/credentials").json()
    assert generic["items"][0]["kinds"] == ["llm"]
    assert generic["items"][0]["is_default"] is True
    card = next(c for c in generic["capabilities"] if c["capability"] == "llm")
    assert card["keys"] == 1


def test_patch_priority_enabled_and_limit(stack: Stack) -> None:
    created = _create(stack)
    response = _call(
        stack,
        "patch",
        f"/me/credentials/{created['id']}",
        json={
            "priority": 5,
            "enabled": False,
            "label": "Не сейчас",
            "monthly_limit": {"minutes": 90, "requests": 100},
        },
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert (updated["priority"], updated["enabled"], updated["label"]) == (
        5,
        False,
        "Не сейчас",
    )
    assert updated["monthly_limit"] == {
        "minutes": 90.0,
        "requests": 100,
        "cost_usd": None,
    }
    cleared = _call(
        stack,
        "patch",
        f"/me/credentials/{created['id']}",
        json={"clear_monthly_limit": True, "enabled": True},
    )
    assert cleared.json()["monthly_limit"] is None


def test_default_key_flag_is_only_for_llm(stack: Stack) -> None:
    created = _create(stack)
    response = _call(
        stack,
        "patch",
        f"/me/credentials/{created['id']}",
        json={"is_default": True},
    )
    assert response.status_code == 422
    assert "ключей моделей" in response.json()["detail"]


def test_delete_removes_key(stack: Stack) -> None:
    created = _create(stack)
    assert _call(stack, "delete", f"/me/credentials/{created['id']}").status_code == 204
    assert _call(stack, "get", "/me/credentials").json()["items"] == []
    # Чужой/удалённый ключ неотличим от несуществующего.
    assert _call(stack, "delete", f"/me/credentials/{created['id']}").status_code == 404


def test_check_marks_auth_failure_and_reenables_after_success(stack: Stack) -> None:
    created = _create(stack)
    stack.valid_keys.discard(DEEPGRAM_KEY)
    failed = _call(stack, "post", f"/me/credentials/{created['id']}/check")
    assert failed.status_code == 200, failed.text
    body = failed.json()
    assert body["ok"] is False
    assert body["capability"] == "speech_to_text"
    assert body["last_error_code"] == "auth"
    assert DEEPGRAM_KEY not in failed.text
    listing = _call(stack, "get", "/me/credentials").json()
    assert listing["items"][0]["enabled"] is False
    assert listing["items"][0]["last_error_code"] == "auth"

    stack.valid_keys.add(DEEPGRAM_KEY)
    restored = _call(stack, "post", f"/me/credentials/{created['id']}/check")
    assert restored.status_code == 200, restored.text
    assert restored.json()["ok"] is True
    listing = _call(stack, "get", "/me/credentials").json()
    assert listing["items"][0]["enabled"] is True
    assert listing["items"][0]["last_error_code"] is None


def test_check_unsupported_capability_is_honest(stack: Stack) -> None:
    """Ключ волны 3 сохраняется в БД, но проверка честно говорит, что адаптера ещё нет."""
    repo = stack.container.repos.credentials
    assert repo is not None
    user_id = stack.user.id
    credential = Credential(
        id=uuid4(),
        user_id=user_id,
        provider="yandex",
        label="Yandex Vision",
        encrypted_key=stack.container.credentials._cipher.encrypt(user_id, OPENAI_KEY),
        key_hint=OPENAI_KEY[-4:],
        kinds=(CredentialKind.VISION,),
        created_at=datetime.now(UTC),
    )
    asyncio.run(repo.save(credential))

    response = _call(stack, "post", f"/me/credentials/{credential.id}/check")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is False
    assert body["capability"] == "vision"
    assert body["last_error_code"] == "unsupported"
    assert OPENAI_KEY not in response.text


# ---------- ревью волны 2: 401 не выключает LLM-ключ, не-LLM скрыт от прежней ручки ----------


def _create_llm(stack: Stack, **extra: Any) -> dict[str, Any]:
    response = _call(
        stack,
        "post",
        "/me/llm-credentials",
        json={"provider": "openai", "api_key": OPENAI_KEY, **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_llm_auth_failure_keeps_key_enabled_and_visible(stack: Stack) -> None:
    """Один 401 не выключает ключ модели: иначе прогон молча уходит на модель сервера."""
    created = _create_llm(stack)
    stack.valid_keys.discard(OPENAI_KEY)
    stack.container.credentials._models.clear()  # без закешированного успешного списка

    models = _call(stack, "get", f"/me/llm-credentials/{created['id']}/models")
    assert models.status_code == 422, models.text

    listed = _call(stack, "get", "/me/credentials").json()["items"][0]
    assert listed["enabled"] is True  # ключ не выключен
    assert listed["last_error_code"] == "auth"
    assert listed["last_error"]
    legacy = _call(stack, "get", "/me/llm-credentials").json()["items"][0]
    assert legacy["last_error"]
    assert legacy["is_default"] is True

    checked = _call(stack, "post", f"/me/credentials/{created['id']}/check")
    assert checked.status_code == 200, checked.text
    assert checked.json()["ok"] is False
    assert checked.json()["last_error_code"] == "auth"
    assert _call(stack, "get", "/me/credentials").json()["items"][0]["enabled"] is True


def test_llm_compat_routes_hide_non_llm_keys(stack: Stack) -> None:
    """Прежняя ручка ключей моделей не правит и не удаляет ключи инструментов (404)."""
    stt = _create(stack)

    patched = _call(stack, "patch", f"/me/llm-credentials/{stt['id']}", json={"label": "x"})
    assert patched.status_code == 404
    deleted = _call(stack, "delete", f"/me/llm-credentials/{stt['id']}")
    assert deleted.status_code == 404
    models = _call(stack, "get", f"/me/llm-credentials/{stt['id']}/models")
    assert models.status_code == 404
    # Ключ инструмента на месте и виден в общем списке.
    generic = _call(stack, "get", "/me/credentials").json()["items"]
    assert [item["id"] for item in generic] == [stt["id"]]


def test_private_stt_base_url_is_422_not_500() -> None:
    """Закреплённый транспорт отклоняет приватный адрес: это 422, а не 500 (ревью волны 2)."""
    settings = _settings(seed_demo_data=False)
    container = build_container(settings)  # без подмены транспорта работает SSRF-защита
    app = create_app(settings, container=container)
    app.dependency_overrides[optional_user] = lambda: ALICE
    with TestClient(app) as client:
        response = client.post(
            f"{API}/me/credentials",
            json={
                "kinds": ["speech_to_text"],
                "provider": "openai_compatible",
                "api_key": OPENAI_KEY,
                "base_url": "https://127.0.0.1:1/v1",
            },
        )
    assert response.status_code == 422, response.text
    assert "безопасност" in response.json()["detail"]
    assert OPENAI_KEY not in response.text
    assert (
        _call(Stack(settings), "get", "/me/credentials").json()["items"] == []
    )  # ключ не сохранён
