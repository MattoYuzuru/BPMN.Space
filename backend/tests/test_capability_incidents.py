"""Стыковка отказа инструментов с техническими вопросами (RFC-0006, шаги 1–2).

Отказ маршрутизации (квота, неверный ключ, неподдержанный материал) из фоновой обработки
источника превращается в неблокирующий технический вопрос проекта через
`TechnicalQuestionService`. Временные и фатальные ошибки вопроса не создают.
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
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
    CapabilityIncident,
    CredentialKind,
)
from app.domain.credentials import Credential
from app.domain.models import (
    Project,
    QuestionActionKind,
    QuestionCategory,
    Source,
    SourceKind,
    SourceStatus,
    TechnicalQuestionKind,
)
from app.infra.repositories.base import Repositories
from app.infra.repositories.memory import InMemoryStore
from app.ingest.media import FfmpegRunner, MediaProbe, MediaTranscriber
from app.main import create_app
from app.services.auth import optional_user
from app.services.capability_incidents import TechnicalQuestionIncidentSink
from app.services.common import Runtime
from app.services.technical_questions import TechnicalQuestionService

API = "/api/v1"
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


async def _repos_with_source() -> tuple[Repositories, Project, Source]:
    store = InMemoryStore()
    repos = store.repositories()
    project = Project(id=uuid4(), title="Процесс", description=None, created_at=NOW, updated_at=NOW)
    source = Source(
        id=uuid4(),
        project_id=project.id,
        kind=SourceKind.FILE,
        title="Совещание 12.10",
        content="",
        status=SourceStatus.FAILED,
        active=True,
        created_at=NOW,
        file_name="meeting.mp3",
        error="Запись не расшифрована",
    )
    await repos.projects.add(project)
    await repos.sources.add(source)
    return repos, project, source


def _sink(repos: Repositories) -> tuple[TechnicalQuestionIncidentSink, TechnicalQuestionService]:
    questions = TechnicalQuestionService(repos, runtime=Runtime(clock=lambda: NOW))
    return TechnicalQuestionIncidentSink(questions, repos), questions


def _incident(
    project_id,
    source_id,
    *,
    reason: str,
    message: str = "«Deepgram (личный)»: закончилась квота",
    done: str | None = "00:00–10:00",
    remaining: str | None = "10:00–20:00",
) -> CapabilityIncident:
    return CapabilityIncident(
        project_id=project_id,
        source_id=source_id,
        capability=Capability.SPEECH_TO_TEXT,
        status="unavailable",
        reason=reason,
        message=message,
        done=done,
        remaining=remaining,
        alternatives=("vision:frames",),
        derivation={"provider": "deepgram", "capability": "speech_to_text"},
    )


@pytest.mark.asyncio
async def test_quota_failure_becomes_unblocking_technical_question() -> None:
    repos, project, source = await _repos_with_source()
    sink, _ = _sink(repos)

    await sink.report(_incident(project.id, source.id, reason="quota_exhausted"))

    questions = await repos.questions.list_by_project(project.id)
    assert len(questions) == 1
    question = questions[0]
    assert question.category is QuestionCategory.TECHNICAL
    assert question.kind is TechnicalQuestionKind.QUOTA_EXHAUSTED
    assert question.blocking is False
    assert question.code.startswith("Q-")
    assert {item.kind for item in question.actions} == {
        QuestionActionKind.OPEN_SETTINGS,
        QuestionActionKind.RETRY,
        QuestionActionKind.CONTINUE_WITHOUT,
    }
    text = question.text
    assert "квота" in text.lower()
    assert "Совещание 12.10" in text
    assert "00:00–10:00" in text
    assert "10:00–20:00" in text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("auth", TechnicalQuestionKind.CREDENTIAL_INVALID),
        ("unsupported", TechnicalQuestionKind.CAPABILITY_MISSING),
        ("capability_missing", TechnicalQuestionKind.CAPABILITY_MISSING),
    ],
)
async def test_reason_maps_to_question_kind(reason: str, expected: TechnicalQuestionKind) -> None:
    repos, project, source = await _repos_with_source()
    sink, _ = _sink(repos)

    await sink.report(_incident(project.id, source.id, reason=reason))

    questions = await repos.questions.list_by_project(project.id)
    assert [question.kind for question in questions] == [expected]


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["transient", "fatal", None])
async def test_transient_and_fatal_do_not_create_questions(reason: str | None) -> None:
    repos, project, source = await _repos_with_source()
    sink, _ = _sink(repos)

    await sink.report(_incident(project.id, source.id, reason=reason or "transient"))

    assert await repos.questions.list_by_project(project.id) == []


@pytest.mark.asyncio
async def test_incident_without_project_is_skipped() -> None:
    repos, _, source = await _repos_with_source()
    sink, _ = _sink(repos)

    # У голосовой заметки вне проекта нет project_id: вопрос создавать некуда.
    await sink.report(_incident(None, source.id, reason="quota_exhausted"))

    assert await repos.questions.list_by_project(source.project_id) == []


# ---------- сквозной путь: загрузка записи → отказ STT → технический вопрос ----------


class _FakeRunner(FfmpegRunner):
    """ffmpeg без процессов: запись из двух сегментов по 10 минут."""

    def __init__(self) -> None:
        super().__init__(ffmpeg="ffmpeg", ffprobe="ffprobe", timeout_sec=5)
        self._probe = MediaProbe(duration_sec=1200, has_audio=True)

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


def _http_settings() -> Settings:
    return Settings(
        mock_delay_scale=0,
        app_env="test",
        auth_enabled=False,
        seed_demo_data=False,
        rate_limit_enabled=False,
        credentials_encryption_key=SecretStr(Fernet.generate_key().decode()),
        stt_provider="deepgram",
        deepgram_api_key=SecretStr("server-dg-key-0123456789"),
        capability_retry_base_sec=0,
        capability_retry_max_sec=0,
    )


def _container_with_quota_failure(
    handler: httpx.MockTransport,
) -> Container:
    container = build_container(_http_settings(), adapter_transport=handler)
    server_stt = container.sources._media._stt  # type: ignore[union-attr]
    container.sources._media = MediaTranscriber(  # type: ignore[assignment]
        server_stt,
        _FakeRunner(),
        segment_sec=600,
        parallel_segments=1,
        provider="deepgram",
        model="nova-3",
    )
    return container


def _quota_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/v1/listen"):
        return httpx.Response(402, json={"error": {"code": "insufficient_quota"}})
    return httpx.Response(200, json={"access_token": "x"})


def _upload_media(client: TestClient) -> tuple[dict, dict]:
    project = client.post(f"{API}/projects", json={"title": "Запись планёрки"}).json()
    uploaded = client.post(
        f"{API}/projects/{project['id']}/sources/file",
        files={"file": ("meeting.mp3", b"audio-bytes", "audio/mpeg")},
    )
    assert uploaded.status_code == 201, uploaded.text
    detail = client.get(f"{API}/projects/{project['id']}").json()
    return uploaded.json(), detail


def test_media_routing_failure_creates_technical_question_over_http() -> None:
    """Реальный контейнер: загрузка записи → отказ всех ключей STT → вопрос в проекте."""
    container = _container_with_quota_failure(httpx.MockTransport(_quota_handler))
    app = create_app(container.settings, container=container)
    try:
        with TestClient(app) as client:
            _, detail = _upload_media(client)

        technical = [
            question for question in detail["questions"] if question["category"] == "technical"
        ]
        assert len(technical) == 1, detail["questions"]
        question = technical[0]
        assert question["kind"] == "quota_exhausted"
        assert question["blocking"] is False
        assert len(question["actions"]) == 3
        assert "meeting.mp3" in question["text"]

        record = next(item for item in detail["sources"] if item["kind"] == "file")
        assert record["status"] == "failed"
        assert record["error"] is not None
        assert "квот" in record["error"].lower()
        assert record["warning"] is not None
        assert "не обработано" in record["warning"]
    finally:
        asyncio.run(container.spawner.shutdown())


def test_user_key_quota_failure_creates_question_with_key_label() -> None:
    """Ключ пользователя-инициатора: вопрос называет ключ, источник предупреждает о покрытии."""
    container = _container_with_quota_failure(httpx.MockTransport(_quota_handler))
    user_id = uuid4()
    credential = Credential(
        id=uuid4(),
        user_id=user_id,
        provider="deepgram",
        label="Deepgram рабочий",
        encrypted_key=container.credentials._cipher.encrypt(user_id, "dg-user-key-0123456789"),
        key_hint="6789",
        kinds=(CredentialKind.SPEECH_TO_TEXT,),
        created_at=NOW,
    )
    asyncio.run(container.repos.credentials.save(credential))  # type: ignore[union-attr]
    app = create_app(container.settings, container=container)
    app.dependency_overrides[optional_user] = lambda: SimpleNamespace(
        id=user_id, email="uploader@example.com"
    )
    try:
        with TestClient(app) as client:
            _, detail = _upload_media(client)

        technical = [
            question for question in detail["questions"] if question["category"] == "technical"
        ]
        assert len(technical) == 1, detail["questions"]
        assert "Deepgram рабочий" in technical[0]["text"]
        assert "квота" in technical[0]["text"].lower()
    finally:
        asyncio.run(container.spawner.shutdown())
