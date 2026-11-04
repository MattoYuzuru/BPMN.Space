"""Распознавание речи на ключах пользователя (RFC-0006, шаг 1).

Ключи инициатора загрузки и вызывающего пользователя, запасной серверный провайдер, структурный
отказ маршрутизации в источнике и `derivation`, а также HTTP-путь Deepgram через подменённый
транспорт. Без сети и без настоящего ffmpeg.
"""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.container import Container, build_container
from app.domain.capabilities import (
    Capability,
    CapabilityError,
    CredentialKind,
    ErrorClass,
)
from app.domain.credentials import Credential
from app.domain.models import Project, SourceStatus
from app.domain.sources import SPEECH_TO_TEXT
from app.infra.crypto import CredentialCipher
from app.infra.repositories.base import Repositories
from app.infra.repositories.memory import InMemoryStore
from app.infra.storage import InMemoryFileStorage
from app.ingest.adapters import AdapterContext, AdapterRegistry, AdapterSpec
from app.ingest.media import FfmpegRunner, MediaProbe, MediaTranscriber
from app.ingest.parsers import LocalDocumentParser
from app.ingest.stt import SpeechToText, Transcript
from app.main import create_app
from app.services.auth import optional_user
from app.services.capability_router import CapabilityRouter, RoutedSpeechToText, RoutingPolicy
from app.services.catalog import TranscriptionService
from app.services.common import Runtime
from app.services.errors import ToolUnavailableError
from app.services.sources import SourceService

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
USER_KEY = "dg-user-secret-0123456789"
SERVER_KEY = "dg-server-secret-0123456789"
API = "/api/v1"


# ---------- обвязка без сети ----------


class _Runner(FfmpegRunner):
    """ffmpeg без процессов: запись из двух сегментов по 10 минут."""

    def __init__(self, *, duration_sec: float = 1200) -> None:
        super().__init__(ffmpeg="ffmpeg", ffprobe="ffprobe", timeout_sec=5)
        self._probe = MediaProbe(duration_sec=duration_sec, has_audio=True)

    @property
    def available(self) -> bool:
        return True

    async def probe(self, source: Path) -> MediaProbe:
        return self._probe

    async def segment(self, source: Path, out_dir: Path, *, segment_sec: int) -> list[Path]:
        paths = []
        for index in range(2):
            path = out_dir / f"segment_{index:05d}.ogg"
            path.write_bytes(f"audio-{index}".encode())
            paths.append(path)
        return paths


class _FakeAdapter:
    """Адаптер распознавания с планом по номеру сегмента: текст или класс ошибки."""

    capability = Capability.SPEECH_TO_TEXT
    provider = "fake"
    model: str | None = "fake-1"

    def __init__(
        self,
        context: AdapterContext,
        plan: dict[str, list[object]],
        calls: list[str],
    ) -> None:
        self.context = context
        self.credential_id = context.credential_id
        self._plan = plan
        self._calls = calls

    async def check(self) -> str:
        return "Ключ действует"

    async def transcribe(self, data: bytes, *, mime: str | None) -> Transcript:
        del mime
        index = data.decode().split("-")[1]
        self._calls.append(self.context.api_key)
        script = self._plan.setdefault(index, [])
        action = script.pop(0) if script else None
        if isinstance(action, BaseException):
            raise action
        if isinstance(action, Transcript):
            return action
        return Transcript(text=f"речь {index}", duration_sec=600, provider="fake", model="fake-1")

    async def aclose(self) -> None:
        return None


class _ServerStt:
    """Серверный провайдер: считает вызовы и падает заданной ошибкой."""

    def __init__(self, *, fail: BaseException | None = None) -> None:
        self.fail = fail or AssertionError("серверный провайдер не должен вызываться")
        self.calls = 0

    async def transcribe(self, data: bytes, *, mime: str | None) -> Transcript:
        del data, mime
        self.calls += 1
        raise self.fail


class _MockServerStt:
    """Запасной серверный путь: готовый ответ (аналог mock-STT в dev)."""

    def __init__(self, text: str = "серверная расшифровка") -> None:
        self.text = text
        self.calls = 0

    async def transcribe(self, data: bytes, *, mime: str | None) -> Transcript:
        del data, mime
        self.calls += 1
        return Transcript(text=self.text, duration_sec=1200)


class _Harness:
    def __init__(
        self,
        *,
        plan: dict[str, list[object]] | None = None,
        server: SpeechToText | None = None,
    ) -> None:
        self.user_id = uuid4()
        self.project = Project(
            id=uuid4(), title="Процесс", description=None, created_at=NOW, updated_at=NOW
        )
        store = InMemoryStore()
        self.repos: Repositories = store.repositories()
        self.cipher = CredentialCipher(
            SecretStr(Fernet.generate_key().decode()), allow_ephemeral=False
        )
        self.plan = plan or {}
        self.adapter_calls: list[str] = []
        self.registry = AdapterRegistry()
        self.registry.register(
            AdapterSpec(
                Capability.SPEECH_TO_TEXT,
                "fake",
                "Fake",
                lambda context: _FakeAdapter(context, self.plan, self.adapter_calls),
            )
        )
        self.server_impl: Any = server or _ServerStt()
        self.server: SpeechToText = self.server_impl
        self.router = CapabilityRouter(
            self.repos,
            cipher=self.cipher,
            registry=self.registry,
            runtime=Runtime(clock=lambda: NOW),
            policy=RoutingPolicy(
                max_attempts=2,
                retry_base_sec=0,
                retry_max_sec=0,
                quota_cooldown_sec=3600,
            ),
            monotonic=lambda: 0.0,
            sleep=_no_sleep,
        )
        self.storage = InMemoryFileStorage()
        self.service: SourceService | None = None
        self.routed = RoutedSpeechToText(self.router, server=self.server)
        self.service = SourceService(
            self.repos,
            parser=LocalDocumentParser(),
            storage=self.storage,
            runtime=Runtime(clock=lambda: NOW),
            max_text_chars=100_000,
            max_upload_bytes=1_000_000,
            parse_delay_sec=0,
            media=MediaTranscriber(
                self.server,
                _Runner(),
                segment_sec=600,
                # Сегменты по одному: покрытие в отказе маршрутизации детерминировано.
                parallel_segments=1,
                attempts=1,
                provider="mock",
            ),
            stt_for_user=self.routed.for_user,
            max_media_bytes=1_000_000,
        )

    async def setup(self, *, with_key: bool = True) -> "_Harness":
        await self.repos.projects.add(self.project)
        if with_key:
            await self._add_stt_credential()
        return self

    async def _add_stt_credential(self) -> Credential:
        credential = Credential(
            id=uuid4(),
            user_id=self.user_id,
            provider="fake",
            label="Deepgram (личный)",
            encrypted_key=self.cipher.encrypt(self.user_id, USER_KEY),
            key_hint=USER_KEY[-4:],
            kinds=(CredentialKind.SPEECH_TO_TEXT,),
            created_at=NOW,
        )
        await self.repos.credentials.save(credential)  # type: ignore[union-attr]
        return credential

    async def upload_and_process(self) -> tuple[Any, Any]:
        assert self.service is not None
        source = await self.service.create_media(
            self.project.id,
            file_name="meeting.mp3",
            mime="audio/mpeg",
            read=_reader(b"media"),
            title=None,
        )
        await self.service.process_file(source.id, initiator_id=self.user_id)
        sources = await self.repos.sources.list_by_project(self.project.id)
        record = next(item for item in sources if item.id == source.id)
        transcript = next(item for item in sources if item.parent_id == source.id)
        return record, transcript


async def _no_sleep(_seconds: float) -> None:
    return None


def _reader(data: bytes):
    chunks = [data, b""]

    async def read(_size: int = -1) -> bytes:
        return chunks.pop(0)

    return read


# ---------- запись на ключе инициатора ----------


async def _make_harness(
    *,
    plan: dict[str, list[object]] | None = None,
    server: SpeechToText | None = None,
    with_key: bool = True,
) -> _Harness:
    harness = _Harness(plan=plan, server=server)
    return await harness.setup(with_key=with_key)


async def test_media_uses_initiator_key_and_writes_derivation_cost() -> None:
    harness = await _make_harness()
    harness.plan["0"] = [Transcript(text="речь 0", duration_sec=600, provider="fake", model="m")]
    harness.plan["1"] = [Transcript(text="речь 1", duration_sec=600, provider="fake", model="m")]

    record, transcript = await harness.upload_and_process()

    assert record.status is SourceStatus.READY
    assert transcript.status is SourceStatus.READY
    assert transcript.content == "[00:00] речь 0\n[10:00] речь 1"
    assert harness.adapter_calls == [USER_KEY, USER_KEY]
    assert harness.server_impl.calls == 0  # серверный провайдер не тронут
    derivation = transcript.derivation
    assert derivation is not None
    assert derivation.capability == SPEECH_TO_TEXT
    assert derivation.provider == "fake"
    assert derivation.model == "m"  # модель адаптера, а не статичная серверная
    assert derivation.cost_usd is None  # провайдер цену не сообщил
    assert derivation.params["minutes"] == 20.0
    assert derivation.params["duration_sec"] == 1200


async def test_media_falls_back_to_server_when_user_has_no_key() -> None:
    server = _MockServerStt("серверная расшифровка")
    harness = await _make_harness(server=server, with_key=False)

    record, transcript = await harness.upload_and_process()

    assert record.status is SourceStatus.READY
    assert transcript.status is SourceStatus.READY
    assert transcript.content == "[00:00] серверная расшифровка\n[10:00] серверная расшифровка"
    assert server.calls == 2
    derivation = transcript.derivation
    assert derivation is not None
    assert derivation.provider == "mock"


async def test_routing_failure_is_explained_and_structured_in_source() -> None:
    harness = await _make_harness(server=_ServerStt(fail=CapabilityError(ErrorClass.AUTH, "нет")))
    harness.plan["0"] = [Transcript(text="речь 0", duration_sec=600, provider="fake")]
    harness.plan["1"] = [CapabilityError(ErrorClass.QUOTA_EXHAUSTED, "квота", retry_after_sec=600)]

    record, transcript = await harness.upload_and_process()

    assert record.status is SourceStatus.FAILED
    assert transcript.status is SourceStatus.FAILED
    assert record.error is not None
    assert "квот" in record.error.lower()
    assert record.warning is not None
    assert "10:00" in record.warning
    derivation = transcript.derivation
    assert derivation is not None
    routing = derivation.params["routing"]
    assert routing["capability"] == SPEECH_TO_TEXT
    assert routing["status"] == "unavailable"
    assert routing["reason"] == "quota_exhausted"  # причина — ключ пользователя
    assert routing["done"] == "00:00–10:00"
    assert routing["remaining"] == "10:00–20:00"


# ---------- голосовая заметка на ключе вызывающего ----------


async def test_voice_note_uses_caller_key() -> None:
    harness = await _make_harness()
    transcription = TranscriptionService(
        harness.server, max_audio_bytes=1_000_000, stt_for_user=harness.routed.for_user
    )

    transcript = await transcription.transcribe(
        b"audio-1", mime="audio/webm", user_id=harness.user_id
    )

    assert transcript.text == "речь 1"
    assert harness.adapter_calls == [USER_KEY]
    assert harness.server_impl.calls == 0


async def test_voice_note_reports_structural_failure() -> None:
    harness = await _make_harness(server=_ServerStt(fail=CapabilityError(ErrorClass.AUTH, "нет")))
    harness.plan["1"] = [CapabilityError(ErrorClass.QUOTA_EXHAUSTED, "квота")]
    transcription = TranscriptionService(
        harness.server, max_audio_bytes=1_000_000, stt_for_user=harness.routed.for_user
    )

    with pytest.raises(ToolUnavailableError) as info:
        await transcription.transcribe(b"audio-1", mime="audio/webm", user_id=harness.user_id)

    assert info.value.reason == "quota_exhausted"  # причина — ключ пользователя, не серверный
    assert info.value.message
    assert USER_KEY not in info.value.message


# ---------- HTTP: Deepgram через подменённый транспорт ----------


class _HttpStack:
    """Контейнер с подменённым HTTP: пользовательский и серверный ключи Deepgram."""

    def __init__(self, settings: Settings) -> None:
        self.requests: list[httpx.Request] = []
        self.user = SimpleNamespace(id=uuid4(), email="user@example.com")
        self.override: httpx.MockTransport | None = None
        self.container: Container = build_container(
            settings, adapter_transport=httpx.MockTransport(self._dispatch)
        )
        self.app = create_app(settings, container=self.container)
        self.app.dependency_overrides[optional_user] = lambda: self.user

    def _dispatch(self, request: httpx.Request) -> httpx.Response:
        if self.override is not None:
            return self.override.handle_request(request)
        return self._handler(request)

    def _handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("/v1/auth/token"):
            return httpx.Response(200, json={"access_token": "x"})
        if request.url.path.endswith("/v1/listen"):
            token = request.headers.get("Authorization", "").removeprefix("Token ")
            if token.startswith("dg-user"):
                return httpx.Response(429, json={"error": {"code": "insufficient_quota"}})
            if token.startswith("dg-server"):
                return httpx.Response(500, text="server down")
            return httpx.Response(200, json={"results": {"channels": []}})
        return httpx.Response(404, text="not found")


def _http_settings(**extra: Any) -> Settings:
    values: dict[str, Any] = {
        "mock_delay_scale": 0,
        "auth_enabled": False,
        "seed_demo_data": False,
        "credentials_encryption_key": SecretStr(Fernet.generate_key().decode()),
        "rate_limit_enabled": False,
        "capability_retry_base_sec": 0,
        "capability_retry_max_sec": 0,
        "stt_provider": "deepgram",
        "deepgram_api_key": SecretStr(SERVER_KEY),
    }
    values.update(extra)
    return Settings(**values)


@pytest.fixture
def http_stack() -> Iterator[_HttpStack]:
    s = _HttpStack(_http_settings())
    with TestClient(s.app):
        yield s


def _add_key(stack: _HttpStack, key: str) -> None:
    repo = stack.container.repos.credentials
    assert repo is not None
    credential = Credential(
        id=uuid4(),
        user_id=stack.user.id,
        provider="deepgram",
        label="Deepgram",
        encrypted_key=stack.container.credentials._cipher.encrypt(stack.user.id, key),
        key_hint=key[-4:],
        kinds=(CredentialKind.SPEECH_TO_TEXT,),
        created_at=datetime.now(UTC),
    )
    asyncio.run(repo.save(credential))


def test_transcription_http_uses_user_key_and_falls_back_to_server(
    http_stack: _HttpStack,
) -> None:
    with TestClient(http_stack.app) as client:
        # Без ключа пользователя — серверный Deepgram (запасной путь), он же отвечает текстом.
        # Серверный ключ должен ответить успешно: подменяем обработчик на время теста.
        healthy = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "metadata": {"duration": 3.0},
                    "results": {"channels": [{"alternatives": [{"transcript": "Серверная речь"}]}]},
                },
            )
        )
        http_stack.override = healthy
        response = client.post(
            f"{API}/transcriptions", files={"file": ("a.webm", b"audio", "audio/webm")}
        )
        assert response.status_code == 200, response.text
        assert response.json()["text"] == "Серверная речь"


def test_transcription_http_reports_capability_failure(
    http_stack: _HttpStack,
) -> None:
    _add_key(http_stack, USER_KEY)
    with TestClient(http_stack.app) as client:
        response = client.post(
            f"{API}/transcriptions", files={"file": ("a.webm", b"audio", "audio/webm")}
        )

    assert response.status_code == 503, response.text
    body = response.json()
    # Причина — ключ пользователя (квота); запасной серверный путь тоже не ответил.
    assert body["code"] == "quota_exhausted"
    assert body["detail"]
    assert USER_KEY not in response.text
    assert SERVER_KEY not in response.text
    assert "alternatives" in body


def test_transcription_http_returns_text_from_user_deepgram_key() -> None:
    settings = _http_settings()
    stack = _HttpStack(settings)
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if request.url.path.endswith("/v1/auth/token"):
            return httpx.Response(200, json={"access_token": "x"})
        return httpx.Response(
            200,
            json={
                "metadata": {"duration": 3.0},
                "results": {"channels": [{"alternatives": [{"transcript": "Пользователь"}]}]},
            },
        )

    stack.override = httpx.MockTransport(handler)
    with TestClient(stack.app) as client:
        _add_key(stack, USER_KEY)
        response = client.post(
            f"{API}/transcriptions", files={"file": ("a.webm", b"audio", "audio/webm")}
        )

    assert response.status_code == 200, response.text
    assert response.json()["text"] == "Пользователь"
    # Ключ пользователя ушёл в Deepgram и не появился в ответе.
    listen = next(request for request in sent if request.url.path.endswith("/v1/listen"))
    assert listen.headers["Authorization"] == f"Token {USER_KEY}"
    assert USER_KEY not in response.text
    del stack
