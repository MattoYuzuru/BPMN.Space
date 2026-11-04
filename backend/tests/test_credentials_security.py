"""Шифрование ключей и защита от SSRF для адресов, которые вводит пользователь."""

import asyncio
import socket
from datetime import UTC, datetime
from uuid import uuid4

import httpcore
import httpx
import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from app.domain.credentials import LlmCredential
from app.infra.crypto import CredentialCipher, CredentialCipherError
from app.infra.repositories.memory import InMemoryLlmCredentialRepository, InMemoryStore
from app.llm.client import LlmConfig
from app.llm.net_guard import UnsafeBaseUrlError, ensure_public_host, normalize_base_url
from app.llm.openai_compatible import OpenAICompatibleClient

SECRET = "sk-ant-api03-PLAINTEXT-SECRET-1234"  # noqa: S105


def _key() -> str:
    return Fernet.generate_key().decode()


def test_roundtrip_hides_plaintext_and_binds_to_user() -> None:
    cipher = CredentialCipher(SecretStr(_key()), allow_ephemeral=False)
    user = uuid4()
    token = cipher.encrypt(user, SECRET)
    assert SECRET.encode() not in token
    assert cipher.decrypt(user, token).get_secret_value() == SECRET
    with pytest.raises(CredentialCipherError, match="другому"):
        cipher.decrypt(uuid4(), token)


def test_rotation_new_key_encrypts_old_keys_still_decrypt() -> None:
    old, new = _key(), _key()
    user = uuid4()
    token = CredentialCipher(SecretStr(old), allow_ephemeral=False).encrypt(user, SECRET)
    rotated = CredentialCipher(SecretStr(f"{new}, {old}"), allow_ephemeral=False)
    assert rotated.decrypt(user, token).get_secret_value() == SECRET
    fresh = rotated.encrypt(user, SECRET)
    only_new = CredentialCipher(SecretStr(new), allow_ephemeral=False)
    assert only_new.decrypt(user, fresh).get_secret_value() == SECRET
    with pytest.raises(CredentialCipherError, match="изменился") as info:
        only_new.decrypt(user, token)
    assert SECRET not in str(info.value)


def test_unset_key_is_unavailable_in_production_and_ephemeral_in_dev(
    caplog: pytest.LogCaptureFixture,
) -> None:
    prod = CredentialCipher(None, allow_ephemeral=False)
    assert not prod.available
    with pytest.raises(CredentialCipherError):
        prod.encrypt(uuid4(), SECRET)
    dev = CredentialCipher(None, allow_ephemeral=True)
    assert dev.available
    assert dev.ephemeral
    assert "CREDENTIALS_ENCRYPTION_KEY" in caplog.text


def test_invalid_key_material_is_rejected_without_echo() -> None:
    with pytest.raises(ValueError, match="Fernet") as info:
        CredentialCipher(SecretStr("not-a-key"), allow_ephemeral=False)
    assert "not-a-key" not in str(info.value)


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.com/v1",  # не HTTPS
        "ftp://api.example.com",
        "https://" + "user" + ":" + "x" + "@api.example.com/v1",
        "https://api.example.com/v1?x=1",
        "https://",
        "javascript:alert(1)",
        "https://api.example.com:99999/v1",
    ],
)
def test_malformed_or_insecure_urls_are_rejected(url: str) -> None:
    with pytest.raises(UnsafeBaseUrlError):
        normalize_base_url(url)


def test_valid_url_is_normalized_and_allowlisted_http_passes() -> None:
    assert normalize_base_url(" https://openrouter.ai/api/v1/ ") == "https://openrouter.ai/api/v1"
    assert (
        normalize_base_url("http://localhost:8000/v1", allowed_private_hosts=["localhost"])
        == "http://localhost:8000/v1"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/v1",
        "https://10.0.0.5/v1",
        "https://192.168.1.10/v1",
        "https://172.16.0.1/v1",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/v1",
        "https://[::ffff:127.0.0.1]/v1",
        "https://[fe80::1]/v1",
        "https://100.64.0.1/v1",
        "https://0.0.0.0/v1",
    ],
)
async def test_private_loopback_link_local_and_metadata_ips_are_rejected(url: str) -> None:
    with pytest.raises(UnsafeBaseUrlError, match="закрытую сеть"):
        await ensure_public_host(url)


async def test_hostname_resolving_to_private_address_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake(_self, host: str, port: int, **_kw):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", port))]

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", fake)
    with pytest.raises(UnsafeBaseUrlError, match="закрытую сеть"):
        await ensure_public_host("https://rebind.example.com/v1")
    await ensure_public_host(
        "https://rebind.example.com/v1", allowed_private_hosts=["rebind.example.com"]
    )


async def test_public_address_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(_self, host: str, port: int, **_kw):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", fake)
    await ensure_public_host("https://api.example.com/v1")


def _resolver_script(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> list[str]:
    """Каждый вызов DNS отдаёт следующий ответ; последний повторяется."""
    calls: list[str] = []

    async def fake(_self, host: str, port: int, **_kw):
        address = answers[min(len(calls), len(answers) - 1)]
        calls.append(address)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", fake)
    return calls


def _record_connects(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    hosts: list[str] = []

    async def fake_connect(_self, host: str, port: int, **_kw):
        hosts.append(host)
        raise httpcore.ConnectError("test: сети нет")

    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", fake_connect)
    return hosts


def _guarded_client(**kw: object) -> OpenAICompatibleClient:
    config = LlmConfig(
        provider="openai_compatible",
        model="m",
        api_key=SecretStr("sk-test"),
        base_url="https://rebind.example.com/v1",
        max_retries=0,
        **kw,  # type: ignore[arg-type]
    )
    return OpenAICompatibleClient(config, guard_host=True)


async def test_connection_goes_to_the_vetted_ip_not_the_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _resolver_script(monkeypatch, ["93.184.216.34"])
    hosts = _record_connects(monkeypatch)
    client = _guarded_client()
    with pytest.raises(RuntimeError, match="связаться"):
        await client.list_models()
    assert hosts == ["93.184.216.34"]


async def test_dns_rebinding_between_check_and_connect_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Первый ответ проходит проверку, второй (при соединении) указывает на метаданные облака.
    _resolver_script(monkeypatch, ["93.184.216.34", "169.254.169.254"])
    hosts = _record_connects(monkeypatch)
    client = _guarded_client()
    with pytest.raises(RuntimeError, match="закрытую сеть"):
        await client.list_models()
    assert hosts == []
    await client.aclose()


async def test_response_over_the_cap_is_aborted_for_chat_and_models() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 5000)

    config = LlmConfig(
        provider="openai_compatible",
        model="m",
        api_key=SecretStr("sk-test"),
        base_url="https://llm.example.test/v1",
        max_retries=0,
        max_response_bytes=1024,
    )
    client = OpenAICompatibleClient(config, transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="слишком большой"):
        await client.complete("s", "u", json_mode=False, max_tokens=10)
    with pytest.raises(RuntimeError, match="слишком большой"):
        await client.list_models()


async def test_chunked_response_without_length_is_aborted_mid_stream() -> None:
    sent = 0

    async def body():
        nonlocal sent
        for _ in range(1000):
            sent += 1
            yield b"y" * 1024

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body())

    config = LlmConfig(
        provider="openai_compatible",
        model="m",
        api_key=SecretStr("sk-test"),
        base_url="https://llm.example.test/v1",
        max_retries=0,
        max_response_bytes=4096,
    )
    client = OpenAICompatibleClient(config, transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="слишком большой"):
        await client.list_models()
    assert sent < 10


async def test_update_does_not_overwrite_concurrent_mark_used() -> None:
    repo = InMemoryLlmCredentialRepository(InMemoryStore())
    user_id, credential_id = uuid4(), uuid4()
    await repo.save(
        LlmCredential(
            id=credential_id,
            user_id=user_id,
            provider="openai",
            label="a",
            base_url=None,
            encrypted_key=b"x",
            key_hint="1234",
            default_model="m",
            is_default=False,
            created_at=datetime.now(UTC),
        )
    )
    stamp = datetime.now(UTC)
    await repo.mark_used(credential_id, stamp, "boom")
    updated = await repo.update_fields(credential_id, label="b")
    assert updated is not None
    assert (updated.label, updated.last_error, updated.last_used_at) == ("b", "boom", stamp)
