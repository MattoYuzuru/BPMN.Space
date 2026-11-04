"""Ключи пользователя на PostgreSQL: права, хранилище и миграция 0020 (RFC-0006).

Маршруты ключей доступны только по cookie-сессии (не по токену доступа). Миграция переносит
старые ключи моделей в обобщённую таблицу без потери данных, а откат возвращает прежнюю схему;
откат при наличии ключей не-LLM типов честно останавливается.

Нужен TEST_DATABASE_URL (см. `make test-postgres`), иначе тесты пропускаются.
"""

# Фикстура `stack` импортируется из test_auth_http: параметры тестов её «переопределяют».
# ruff: noqa: F811

import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.test_auth_http import API, Stack, stack  # noqa: F401 — фикстура подключается импортом

pytestmark = pytest.mark.asyncio
MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"
DEEPGRAM_KEY = "dg-pg-secret-0123456789"


def _deepgram_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/auth/token"):
            return httpx.Response(200, json={"access_token": "x"})
        if request.url.path.endswith("/v1/listen"):
            return httpx.Response(
                200,
                json={
                    "metadata": {"duration": 2.0},
                    "results": {"channels": [{"alternatives": [{"transcript": "Проверить"}]}]},
                },
            )
        return httpx.Response(404, text="not found")

    return httpx.MockTransport(handler)


def _fake_adapter_client() -> Any:
    transport = _deepgram_transport()

    def factory(base_url: str, user_supplied: bool, timeout_sec: float) -> httpx.AsyncClient:
        del user_supplied, timeout_sec
        return httpx.AsyncClient(base_url=base_url, transport=transport)

    return factory


async def _issue(owner: Any) -> str:
    created = await owner.post(
        "/me/api-tokens",
        json={"name": "Агент", "scopes": ["projects:read"]},
    )
    assert created.status_code == 201, created.text
    return created.json()["secret"]


async def test_credentials_are_cookie_only_and_stored_in_postgres(stack: Stack) -> None:
    owner = await stack.user("credentials-owner@example.com")
    injected = stack.app.state.container.credentials
    injected._adapter_client_factory = _fake_adapter_client()  # type: ignore[attr-defined]

    created = await owner.post(
        "/me/credentials",
        json={
            "kinds": ["speech_to_text"],
            "provider": "deepgram",
            "api_key": DEEPGRAM_KEY,
            "label": "Deepgram (личный)",
            "priority": 10,
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["kinds"] == ["speech_to_text"]
    assert DEEPGRAM_KEY not in created.text

    listing = await owner.get("/me/credentials")
    assert listing.status_code == 200, listing.text
    assert [item["id"] for item in listing.json()["items"]] == [body["id"]]
    card = next(
        item for item in listing.json()["capabilities"] if item["capability"] == "speech_to_text"
    )
    assert card["available"] is True

    patched = await owner.patch(
        f"/me/credentials/{body['id']}", json={"priority": 3, "enabled": False}
    )
    assert patched.status_code == 200
    assert (patched.json()["priority"], patched.json()["enabled"]) == (3, False)

    # Хранится шифртекст, а не открытый ключ: проверяем строку в PostgreSQL.
    async with stack.database.sessions() as session:
        row = (
            await session.execute(
                text(
                    "SELECT kinds, provider, priority, enabled, encrypted_key, label "
                    "FROM user_credentials WHERE id = :id"
                ),
                {"id": body["id"]},
            )
        ).one()
    assert row.kinds == ["speech_to_text"]
    assert row.provider == "deepgram"
    assert row.enabled is False
    assert DEEPGRAM_KEY.encode() not in bytes(row.encrypted_key)

    # По токену доступа управлять ключами нельзя — как и моделями (RFC-0007).
    secret = await _issue(owner)
    agent = AsyncClient(transport=ASGITransport(app=stack.app), base_url="http://t")
    headers = {"authorization": f"Bearer {secret}"}
    for response in (
        await agent.get(f"{API}/me/credentials", headers=headers),
        await agent.post(
            f"{API}/me/credentials",
            headers=headers,
            json={"kinds": ["speech_to_text"], "provider": "deepgram", "api_key": DEEPGRAM_KEY},
        ),
        await agent.post(f"{API}/me/credentials/{body['id']}/check", headers=headers),
        await agent.get(f"{API}/me/llm-credentials", headers=headers),
    ):
        assert response.status_code == 403, response.text
        assert "токен" in response.text.lower()
    await agent.aclose()

    deleted = await owner.delete(f"/me/credentials/{body['id']}")
    assert deleted.status_code == 204
    assert (await owner.get("/me/credentials")).json()["items"] == []


async def _migration_config() -> tuple[Any, Any, Config, str, Any]:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL не задан; PostgreSQL-интеграционный тест пропущен")
    schema = f"test_{uuid4().hex}"
    admin = create_async_engine(url)
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return admin, engine, config, schema, url


async def _drop(admin: Any, engine: Any, schema: str) -> None:
    await engine.dispose()
    async with admin.begin() as connection:
        await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    await admin.dispose()


async def test_migration_0020_moves_llm_keys_and_back() -> None:
    admin, engine, config, schema, url = await _migration_config()
    del url

    def migrate(sync_connection: Any, action: str, revision: str) -> None:
        config.attributes["connection"] = sync_connection
        getattr(command, action)(config, revision)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(migrate, "upgrade", "0017_api_tokens")
            user_id = uuid4()
            credential_id = uuid4()
            await connection.execute(
                text(
                    "INSERT INTO users (id, email, hashed_password, is_active, is_superuser, "
                    "is_verified) VALUES (:id, 'legacy@example.com', 'x', true, false, false)"
                ),
                {"id": user_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO user_llm_credentials (id, user_id, provider, label, base_url, "
                    "encrypted_key, key_hint, default_model, is_default, created_at, "
                    "last_used_at, last_error) VALUES (:id, :user, 'openai', 'Старый', NULL, "
                    ":key, '1234', 'gpt-4o', true, now(), now(), 'старая ошибка')"
                ),
                {"id": credential_id, "user": user_id, "key": b"ciphertext-bytes"},
            )

            await connection.run_sync(migrate, "upgrade", "head")
            tables = await connection.run_sync(lambda sync: set(inspect(sync).get_table_names()))
            assert "user_credentials" in tables
            assert "user_llm_credentials" not in tables
            row = (
                await connection.execute(
                    text(
                        "SELECT kinds, provider, label, encrypted_key, default_model, "
                        "is_default, priority, enabled, last_error "
                        "FROM user_credentials WHERE id = :id"
                    ),
                    {"id": credential_id},
                )
            ).one()
            assert row.kinds == ["llm"]
            assert (row.provider, row.label) == ("openai", "Старый")
            assert bytes(row.encrypted_key) == b"ciphertext-bytes"
            assert (row.default_model, row.is_default) == ("gpt-4o", True)
            assert (row.priority, row.enabled) == (100, True)
            assert row.last_error == "старая ошибка"

            await connection.run_sync(migrate, "downgrade", "0017_api_tokens")
            tables = await connection.run_sync(lambda sync: set(inspect(sync).get_table_names()))
            assert "user_llm_credentials" in tables
            assert "user_credentials" not in tables
            old = (
                await connection.execute(
                    text(
                        "SELECT provider, label, key_hint, default_model, is_default, last_error "
                        "FROM user_llm_credentials WHERE id = :id"
                    ),
                    {"id": credential_id},
                )
            ).one()
            assert (old.provider, old.label, old.key_hint) == ("openai", "Старый", "1234")
            assert (old.default_model, old.is_default) == ("gpt-4o", True)
    finally:
        await _drop(admin, engine, schema)


async def test_migration_0020_downgrade_refuses_to_drop_non_llm_keys() -> None:
    admin, engine, config, schema, url = await _migration_config()
    del url

    def migrate(sync_connection: Any, action: str, revision: str) -> None:
        config.attributes["connection"] = sync_connection
        getattr(command, action)(config, revision)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(migrate, "upgrade", "head")
            user_id = uuid4()
            await connection.execute(
                text(
                    "INSERT INTO users (id, email, hashed_password, is_active, is_superuser, "
                    "is_verified) VALUES (:id, 'stt@example.com', 'x', true, false, false)"
                ),
                {"id": user_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO user_credentials (id, user_id, kinds, provider, label, "
                    "encrypted_key, key_hint, priority, enabled, is_default, created_at) "
                    "VALUES (:id, :user, ARRAY['speech_to_text']::varchar[], 'deepgram', 'STT', "
                    ":key, '1234', 100, true, false, now())"
                ),
                {"id": uuid4(), "user": user_id, "key": b"ciphertext"},
            )
            with pytest.raises(RuntimeError, match="невозможен"):
                await connection.run_sync(migrate, "downgrade", "0017_api_tokens")
    finally:
        await _drop(admin, engine, schema)
