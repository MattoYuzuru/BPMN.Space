"""Шифрование ключей и защита от SSRF для адресов, которые вводит пользователь."""

import asyncio
import socket
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from app.infra.crypto import CredentialCipher, CredentialCipherError
from app.llm.net_guard import UnsafeBaseUrlError, ensure_public_host, normalize_base_url

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
