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
from sqlalchemy.exc import IntegrityError
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


async def test_migration_0020_keeps_legacy_table_and_rolls_llm_keys_back() -> None:
    """0020 не удаляет legacy-таблицу; downgrade возвращает в неё и ключи, созданные после."""
    admin, engine, config, schema, url = await _migration_config()
    del url

    def migrate(sync_connection: Any, action: str, revision: str) -> None:
        config.attributes["connection"] = sync_connection
        getattr(command, action)(config, revision)

    def tables(sync_connection: Any) -> set[str]:
        return set(inspect(sync_connection).get_table_names())

    try:
        async with engine.begin() as connection:
            await connection.run_sync(migrate, "upgrade", "0017_api_tokens")
            user_id = uuid4()
            new_user_id = uuid4()
            credential_id = uuid4()
            new_credential_id = uuid4()
            for uid, email in ((user_id, "legacy@example.com"), (new_user_id, "new@example.com")):
                await connection.execute(
                    text(
                        "INSERT INTO users (id, email, hashed_password, is_active, is_superuser, "
                        "is_verified) VALUES (:id, :email, 'x', true, false, false)"
                    ),
                    {"id": uid, "email": email},
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
            tables_now = await connection.run_sync(tables)
            assert "user_credentials" in tables_now
            # Legacy-таблица сохранена: откат только кода должен запускать старый релиз.
            assert "user_llm_credentials" in tables_now
            legacy_rows = (
                await connection.execute(
                    text("SELECT id FROM user_llm_credentials WHERE id = :id"),
                    {"id": credential_id},
                )
            ).all()
            assert legacy_rows == [(credential_id,)]
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

            # Ключ, созданный после релиза: только в новой таблице. И ключ инструмента.
            await connection.execute(
                text(
                    "INSERT INTO user_credentials (id, user_id, kinds, provider, label, "
                    "encrypted_key, key_hint, default_model, priority, enabled, is_default, "
                    "created_at) VALUES (:id, :user, ARRAY['llm']::varchar[], 'openai', "
                    "'Новый', :key, '5678', 'gpt-4o', 10, true, true, now())"
                ),
                {"id": new_credential_id, "user": new_user_id, "key": b"new-cipher"},
            )
            await connection.execute(
                text(
                    "INSERT INTO user_credentials (id, user_id, kinds, provider, label, "
                    "encrypted_key, key_hint, priority, enabled, is_default, created_at) "
                    "VALUES (:id, :user, ARRAY['speech_to_text']::varchar[], 'deepgram', 'STT', "
                    ":key, '1234', 100, true, false, now())"
                ),
                {"id": uuid4(), "user": user_id, "key": b"stt-cipher"},
            )

            await connection.run_sync(migrate, "downgrade", "0019_technical_questions")
            tables_now = await connection.run_sync(tables)
            assert "user_credentials" not in tables_now
            assert "user_llm_credentials" in tables_now
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
            # Ключ модели, созданный после релиза, перенесён обратно (и стал по умолчанию).
            created = (
                await connection.execute(
                    text(
                        "SELECT user_id, provider, label, key_hint, is_default "
                        "FROM user_llm_credentials WHERE id = :id"
                    ),
                    {"id": new_credential_id},
                )
            ).one()
            assert (created.user_id, created.provider, created.label) == (
                new_user_id,
                "openai",
                "Новый",
            )
            assert created.is_default is True
            # Ключи инструментов в прежней схеме не представлены: откат их не сохраняет.
            instrument = (
                await connection.execute(
                    text("SELECT count(*) FROM user_llm_credentials WHERE label = 'STT'")
                )
            ).scalar_one()
            assert instrument == 0
    finally:
        await _drop(admin, engine, schema)


async def test_downgrade_0019_converts_waiting_runs_to_failed() -> None:
    """Старый код не знает RunStatus.waiting: откат 0019 закрывает ожидающие прогоны."""
    admin, engine, config, schema, url = await _migration_config()
    del url

    def migrate(sync_connection: Any, action: str, revision: str) -> None:
        config.attributes["connection"] = sync_connection
        getattr(command, action)(config, revision)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(migrate, "upgrade", "head")
            user_id, project_id, run_id = uuid4(), uuid4(), uuid4()
            await connection.execute(
                text(
                    "INSERT INTO users (id, email, hashed_password, is_active, is_superuser, "
                    "is_verified) VALUES (:id, 'wait@example.com', 'x', true, false, false)"
                ),
                {"id": user_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO projects (id, title, created_at, updated_at, public_read_only) "
                    "VALUES (:id, 'Ожидание', now(), now(), false)"
                ),
                {"id": project_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO runs (id, project_id, mode, status, started_at, progress, "
                    "warnings) VALUES (:id, :project, 'analyze', 'waiting', now(), 0, "
                    "'[]'::jsonb)"
                ),
                {"id": run_id, "project": project_id},
            )

            await connection.run_sync(migrate, "downgrade", "0018_llm_call_cost")
            run = (
                await connection.execute(
                    text("SELECT status, error, finished_at FROM runs WHERE id = :id"),
                    {"id": run_id},
                )
            ).one()
            assert run.status == "failed"
            assert run.error is not None
            assert "откате" in run.error
            assert run.finished_at is not None
            columns = await connection.run_sync(
                lambda sync: {item["name"] for item in inspect(sync).get_columns("questions")}
            )
            assert "category" not in columns
            assert "actions" not in columns
            assert "blocking" not in columns
    finally:
        await _drop(admin, engine, schema)


async def test_migration_0027_adds_wire_api_only_for_compatible_keys() -> None:
    """ADR-0013: старые ключи остаются Chat (NULL), протокол — только у совместимого провайдера."""
    admin, engine, config, schema, url = await _migration_config()
    del url

    def migrate(sync_connection: Any, action: str, revision: str) -> None:
        config.attributes["connection"] = sync_connection
        getattr(command, action)(config, revision)

    insert = text(
        "INSERT INTO user_credentials (id, user_id, kinds, provider, label, base_url, "
        "encrypted_key, key_hint, created_at) VALUES (:id, :user, ARRAY['llm']::varchar[], "
        ":provider, 'Ключ', :url, :key, '1234', now())"
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(migrate, "upgrade", "0026_agent_search_limit")
            user_id = uuid4()
            await connection.execute(
                text(
                    "INSERT INTO users (id, email, hashed_password, is_active, is_superuser, "
                    "is_verified) VALUES (:id, 'wire@example.com', 'x', true, false, false)"
                ),
                {"id": user_id},
            )
            old_id = uuid4()
            await connection.execute(
                insert,
                {
                    "id": old_id,
                    "user": user_id,
                    "provider": "openai_compatible",
                    "url": "https://api.deepseek.com",
                    "key": b"ciphertext",
                },
            )
            await connection.run_sync(migrate, "upgrade", "head")
            wire = (
                await connection.execute(
                    text("SELECT wire_api FROM user_credentials WHERE id = :id"), {"id": old_id}
                )
            ).scalar_one()
            assert wire is None
            await connection.execute(
                text("UPDATE user_credentials SET wire_api = 'responses' WHERE id = :id"),
                {"id": old_id},
            )
        async with engine.begin() as connection:
            fixed_id = uuid4()
            await connection.execute(
                insert,
                {
                    "id": fixed_id,
                    "user": user_id,
                    "provider": "openai",
                    "url": None,
                    "key": b"ciphertext",
                },
            )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text("UPDATE user_credentials SET wire_api = 'responses' WHERE id = :id"),
                        {"id": fixed_id},
                    )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text("UPDATE user_credentials SET wire_api = 'grpc' WHERE id = :id"),
                        {"id": old_id},
                    )
            await connection.run_sync(migrate, "downgrade", "0026_agent_search_limit")
            columns = await connection.run_sync(
                lambda sync: {c["name"] for c in inspect(sync).get_columns("user_credentials")}
            )
            assert "wire_api" not in columns
    finally:
        await _drop(admin, engine, schema)
