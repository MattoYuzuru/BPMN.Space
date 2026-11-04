"""Производные источники и дерево материалов (RFC-0006, шаг 3).

Запись → исходный файл + производная расшифровка, состав контекста прогона, каскадное
удаление, отметка правки человеком, совместимость хеша снимка со старыми прогонами и
миграция 0016 (PostgreSQL-часть требует TEST_DATABASE_URL).
"""

import asyncio
import hashlib
import json
import os
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from app.domain.models import (
    Project,
    Quote,
    Source,
    SourceDerivation,
    SourceKind,
    SourceOrigin,
    SourceStatus,
    SourceTrust,
)
from app.domain.questions import find_source_with_quote
from app.domain.sources import SPEECH_TO_TEXT, descendants
from app.infra.repositories.base import Repositories
from app.infra.repositories.memory import InMemoryStore
from app.infra.repositories.sql import SqlStore
from app.infra.seed import build_seed
from app.infra.storage import LocalFileStorage
from app.ingest.context import build_run_context, source_snapshot_hash
from app.ingest.media import FfmpegRunner, MediaJob, MediaProbe, MediaTranscriber
from app.ingest.parsers import LocalDocumentParser
from app.ingest.stt import MockSpeechToText, Transcript
from app.services.assistant import AssistantService
from app.services.common import Runtime
from app.services.errors import ConflictError, InvalidInputError
from app.services.sources import TRANSCRIPT_MISSING, SourceService
from tests.conftest import API, create_project

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"
NOW = datetime(2026, 11, 4, 10, 0, tzinfo=UTC)


class _Runner(FfmpegRunner):
    """ffmpeg без процессов: заданный probe и два сегмента «звука»."""

    def __init__(self, probe: MediaProbe) -> None:
        super().__init__(ffmpeg="ffmpeg", ffprobe="ffprobe", timeout_sec=5)
        self._probe = probe

    @property
    def available(self) -> bool:
        return True

    async def probe(self, source: Path) -> MediaProbe:
        return self._probe

    async def segment(self, source: Path, out_dir: Path, *, segment_sec: int) -> list[Path]:
        paths = []
        for index in range(2):
            path = out_dir / f"segment_{index:05d}.ogg"
            path.write_bytes(f"audio-{index}".encode() * 50)
            paths.append(path)
        return paths


def _reader(data: bytes):
    chunks = [data, b""]

    async def read(_size: int = -1) -> bytes:
        return chunks.pop(0)

    return read


def _stored_media(root: Path) -> bool:
    return any(root.rglob("*.mp4"))


class _CountingStt(MockSpeechToText):
    def __init__(self) -> None:
        super().__init__(delay_sec=0)
        self.calls = 0

    async def transcribe(self, data: bytes, *, mime: str | None) -> Transcript:
        self.calls += 1
        return await super().transcribe(data, mime=mime)


def _build(
    repos: Repositories,
    tmp_path: Path,
    probe: MediaProbe | None = None,
    stt: MockSpeechToText | None = None,
) -> SourceService:
    runner = _Runner(probe or MediaProbe(duration_sec=900, has_audio=True, has_video=True))
    media = MediaTranscriber(
        stt or MockSpeechToText(delay_sec=0), runner, segment_sec=600, provider="mock", model=None
    )
    return SourceService(
        repos,
        parser=LocalDocumentParser(),
        storage=LocalFileStorage(tmp_path),
        runtime=Runtime(),
        max_text_chars=100_000,
        max_upload_bytes=1_000_000,
        parse_delay_sec=0,
        media=media,
    )


async def _service(
    tmp_path: Path, probe: MediaProbe | None = None, stt: MockSpeechToText | None = None
) -> tuple[SourceService, InMemoryStore, Project]:
    store = InMemoryStore()
    repos = store.repositories()
    project = Project(id=uuid4(), title="Запись", description=None, created_at=NOW, updated_at=NOW)
    await repos.projects.add(project)
    return _build(repos, tmp_path, probe, stt), store, project


async def _upload(service: SourceService, project: Project) -> tuple[Source, Source]:
    parent = await service.create_media(
        project.id,
        file_name="демо.mp4",
        mime="video/mp4",
        read=_reader(b"\x00" * 2048),
        title=None,
    )
    await service.process_file(parent.id)
    sources = await service._repos.sources.list_by_project(project.id)
    stored = next(s for s in sources if s.id == parent.id)
    child = next(s for s in sources if s.parent_id == parent.id)
    return stored, child


# ---------- запись → исходный файл + расшифровка ----------


async def test_media_upload_creates_parent_file_and_derived_transcript(tmp_path: Path) -> None:
    service, _, project = await _service(tmp_path)
    parent, child = await _upload(service, project)

    assert parent.kind is SourceKind.FILE
    assert parent.origin is SourceOrigin.USER
    assert parent.trust is SourceTrust.PRIMARY
    assert parent.status is SourceStatus.READY
    assert parent.content == ""
    assert parent.duration_sec == 900
    assert parent.media is not None
    assert parent.media.has_audio is True
    assert parent.media.has_video is True
    assert not parent.feeds_model

    assert child.origin is SourceOrigin.DERIVED
    assert child.trust is SourceTrust.EXTRACTED
    assert child.parent_id == parent.id
    assert child.project_id == project.id
    assert child.status is SourceStatus.READY
    assert child.edited_by_human is False
    assert child.content.startswith("[00:00] ")
    assert "\n[10:00] " in child.content
    assert child.title == "Расшифровка: демо.mp4"
    assert child.derivation is not None
    assert child.derivation.capability == SPEECH_TO_TEXT
    assert child.derivation.provider == "mock"
    assert child.derivation.params["segment_sec"] == 600
    assert child.derivation.params["duration_sec"] == 900
    assert child.feeds_model


async def test_media_failure_is_visible_on_parent_and_transcript(tmp_path: Path) -> None:
    service, _, project = await _service(
        tmp_path, MediaProbe(duration_sec=12, has_audio=False, has_video=True)
    )
    parent, child = await _upload(service, project)
    assert parent.status is SourceStatus.FAILED
    assert child.status is SourceStatus.FAILED
    assert parent.error == child.error
    assert parent.error is not None
    assert "нет звуковой дорожки" in parent.error
    # ffprobe успел прочитать файл: дорожки записи видны и при сбое расшифровки.
    assert parent.media is not None
    assert parent.media.has_video is True

    context = build_run_context(
        project=Project(
            id=project.id, title=project.title, description=None, created_at=NOW, updated_at=NOW
        ),
        sources=[parent, child],
        questions=[],
        versions=[],
    )
    assert context.evidence_sources == []
    assert context.analysis_input_complete is False
    # Сбой записи и расшифровки — один недоступный материал, а не два.
    assert any("без готового текста: 1." in warning for warning in context.warnings)


async def test_failed_transcript_typed_by_hand_marks_edit_and_recovers_parent(
    tmp_path: Path,
) -> None:
    service, store, project = await _service(
        tmp_path, MediaProbe(duration_sec=12, has_audio=False, has_video=True)
    )
    parent, child = await _upload(service, project)
    fixed = await service.update(
        child.id,
        title=None,
        content="[00:00] Диспетчер согласует заявку.",
        active=None,
        fields={"content"},
    )
    assert fixed.status is SourceStatus.READY
    assert fixed.edited_by_human is True
    assert store.sources[parent.id].status is SourceStatus.READY
    assert store.sources[parent.id].error is None


# ---------- правка, выключение, удаление ----------


async def test_editing_derived_text_marks_edited_by_human(tmp_path: Path) -> None:
    service, _, project = await _service(tmp_path)
    parent, child = await _upload(service, project)

    renamed = await service.update(
        child.id, title="Расшифровка совещания", content=None, active=None, fields={"title"}
    )
    assert renamed.edited_by_human is False
    same = await service.update(
        child.id, title=None, content=child.content, active=None, fields={"content"}
    )
    assert same.edited_by_human is False  # тот же текст — не правка

    edited = await service.update(
        child.id,
        title=None,
        content=f"{child.content}\n[14:00] Уточнение аналитика.",
        active=None,
        fields={"content"},
    )
    assert edited.edited_by_human is True
    assert edited.origin is SourceOrigin.DERIVED
    assert edited.trust is SourceTrust.EXTRACTED

    with pytest.raises(InvalidInputError, match="нет своего текста"):
        await service.update(
            parent.id, title=None, content="текст записи", active=None, fields={"content"}
        )


async def test_user_text_edit_does_not_set_edited_by_human(tmp_path: Path) -> None:
    service, _, project = await _service(tmp_path)
    source = await service.create_text(
        project.id,
        content="Инженер проверяет заявку.",
        title=None,
        kind=SourceKind.TEXT,
        duration_sec=None,
    )
    edited = await service.update(
        source.id, title=None, content="Инженер проверяет акт.", active=None, fields={"content"}
    )
    assert edited.origin is SourceOrigin.USER
    assert edited.edited_by_human is False


async def test_toggling_parent_toggles_derived(tmp_path: Path) -> None:
    service, store, project = await _service(tmp_path)
    parent, child = await _upload(service, project)
    await service.update(parent.id, title=None, content=None, active=False, fields={"active"})
    assert store.sources[child.id].active is False
    await service.update(parent.id, title=None, content=None, active=True, fields={"active"})
    assert store.sources[child.id].active is True
    # Потомка можно выключить отдельно: родитель не меняется.
    await service.update(child.id, title=None, content=None, active=False, fields={"active"})
    assert store.sources[parent.id].active is True


async def test_delete_parent_cascades_to_derived_and_file(tmp_path: Path) -> None:
    service, store, project = await _service(tmp_path)
    parent, child = await _upload(service, project)
    assert parent.file_key is not None
    assert _stored_media(tmp_path)

    await service.delete(parent.id)
    assert parent.id not in store.sources
    assert child.id not in store.sources
    assert not _stored_media(tmp_path)


async def test_delete_derived_keeps_parent(tmp_path: Path) -> None:
    service, store, project = await _service(tmp_path)
    parent, child = await _upload(service, project)
    await service.delete(child.id)
    assert parent.id in store.sources
    assert child.id not in store.sources


def test_descendants_walks_grandchildren_once() -> None:
    root = _source("root")
    child = _source("child", parent_id=root.id)
    grandchild = _source("grand", parent_id=child.id)
    other = _source("other")
    assert [s.id for s in descendants([grandchild, other, child, root], root.id)] == [
        child.id,
        grandchild.id,
    ]


async def test_parent_must_be_in_same_project(tmp_path: Path) -> None:
    from app.services.sources import _ensure_parent  # noqa: PLC0415

    service, store, project = await _service(tmp_path)
    repos = store.repositories()
    foreign = _source("чужой", project_id=uuid4())
    await repos.sources.add(foreign)
    orphan = _source("потомок", project_id=project.id, parent_id=foreign.id)
    with pytest.raises(InvalidInputError, match="не найден в этом проекте"):
        await _ensure_parent(repos, orphan, [orphan])
    missing = _source("потомок", project_id=project.id, parent_id=uuid4())
    with pytest.raises(InvalidInputError):
        await _ensure_parent(repos, missing, [missing])
    selfish = _source("сам себе")
    selfish.parent_id = selfish.id
    with pytest.raises(InvalidInputError, match="самого себя"):
        await _ensure_parent(repos, selfish, [selfish])
    assert service is not None


# ---------- контекст прогона ----------


def _source(
    title: str,
    *,
    content: str = "",
    project_id: UUID | None = None,
    parent_id: UUID | None = None,
    kind: SourceKind = SourceKind.TEXT,
    trust: SourceTrust = SourceTrust.PRIMARY,
    origin: SourceOrigin = SourceOrigin.USER,
    status: SourceStatus = SourceStatus.READY,
    offset: int = 0,
) -> Source:
    return Source(
        id=uuid4(),
        project_id=project_id or UUID(int=1),
        kind=kind,
        title=title,
        content=content,
        status=status,
        active=True,
        created_at=NOW + timedelta(seconds=offset),
        parent_id=parent_id,
        trust=trust,
        origin=origin,
    )


def _project() -> Project:
    return Project(id=UUID(int=1), title="П", description=None, created_at=NOW, updated_at=NOW)


def test_run_context_takes_transcript_but_not_media_parent_or_summary() -> None:
    record = _source("встреча.mp4", kind=SourceKind.FILE)
    transcript = _source(
        "Расшифровка",
        content="[00:00] Диспетчер согласует заявку за семь дней.",
        parent_id=record.id,
        trust=SourceTrust.EXTRACTED,
        origin=SourceOrigin.DERIVED,
        offset=1,
    )
    summary = _source(
        "Кратко",
        content="Диспетчер согласует заявку.",
        parent_id=record.id,
        trust=SourceTrust.SUMMARY,
        origin=SourceOrigin.DERIVED,
        offset=2,
    )
    rules = _source("Регламент", content="Инженер готовит заявку.", offset=3)
    context = build_run_context(
        project=_project(), sources=[record, transcript, summary, rules], questions=[], versions=[]
    )
    assert context.evidence_sources is not None
    assert [s.id for s in context.evidence_sources] == [transcript.id, rules.id]
    assert [s.id for s in context.sources] == [transcript.id, rules.id]
    assert context.analysis_input_complete is True
    # Основание из записи ссылается на расшифровку — источник, где лежит текст.
    found = find_source_with_quote("Диспетчер согласует заявку", context.evidence_sources)
    assert found is not None
    assert found.id == transcript.id


# ---------- хеш снимка и восстановление старых прогонов ----------


def _legacy_snapshot_hash(sources: Sequence[Source]) -> str:
    """Алгоритм `source_snapshot_hash` до миграции 0016 (копия для проверки совместимости)."""

    def digest(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    values = sorted(
        [
            (
                str(s.id),
                s.kind.value,
                s.title,
                s.status.value,
                s.active,
                digest(s.content),
                str(s.question_id),
                s.created_at.isoformat(),
            )
            for s in sources
        ]
    )
    return digest(json.dumps(values, ensure_ascii=False))


def test_snapshot_hash_of_legacy_sources_is_unchanged() -> None:
    answer = _source("Ответ", content="Да, диспетчер.", kind=SourceKind.ANSWER)
    assert answer.origin is SourceOrigin.ANSWER  # ответ всегда origin=answer
    legacy = [
        _source("Регламент", content="Инженер готовит заявку."),
        answer,
        _source("Голос", content="Записываю по итогам.", kind=SourceKind.VOICE, offset=5),
        _source("Скан", kind=SourceKind.FILE, status=SourceStatus.PROCESSING, offset=9),
    ]
    # Прогон, запущенный до обновления, сохранил старый хеш: после миграции он совпадает,
    # и _check_recovered_input не отклоняет восстановленный прогон.
    assert source_snapshot_hash(legacy) == _legacy_snapshot_hash(legacy)


def test_snapshot_hash_tracks_lineage_fields() -> None:
    record = _source("встреча.mp4", kind=SourceKind.FILE)
    transcript = _source(
        "Расшифровка",
        content="[00:00] Реплика.",
        parent_id=record.id,
        trust=SourceTrust.EXTRACTED,
        origin=SourceOrigin.DERIVED,
    )
    transcript.derivation = SourceDerivation(
        capability=SPEECH_TO_TEXT, provider="mock", created_at=NOW, params={"segment_sec": 600}
    )
    before = source_snapshot_hash([record, transcript])
    assert before != _legacy_snapshot_hash([record, transcript])
    transcript.edited_by_human = True
    assert source_snapshot_hash([record, transcript]) != before
    transcript.edited_by_human = False
    transcript.trust = SourceTrust.SUMMARY
    assert source_snapshot_hash([record, transcript]) != before


# ---------- API ----------


def test_api_exposes_lineage_and_rejects_manual_parent(client: TestClient) -> None:
    project_id = create_project(client)
    url = f"{API}/projects/{project_id}/sources/text"
    created = client.post(url, json={"content": "Инженер готовит заявку."})
    assert created.status_code == 201
    body = created.json()
    assert body["origin"] == "user"
    assert body["trust"] == "primary"
    assert body["parent_id"] is None
    assert body["derivation"] is None
    assert body["edited_by_human"] is False

    forged = client.post(url, json={"content": "Чужой потомок.", "parent_id": body["id"]})
    assert forged.status_code == 422
    forged = client.post(url, json={"content": "Свой потомок.", "origin": "derived"})
    assert forged.status_code == 422


# ---------- PostgreSQL: миграция 0016 и FK ----------


async def test_migration_0016_backfills_origin_and_keeps_snapshot_hash() -> None:
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

    def migrate(target: str):
        def run(sync_connection) -> None:
            config.attributes["connection"] = sync_connection
            command.upgrade(config, target)

        return run

    project_id, text_id, answer_id = uuid4(), uuid4(), uuid4()
    try:
        async with engine.begin() as connection:
            await connection.run_sync(migrate("0015_version_sessions"))
            await connection.execute(
                text(
                    "INSERT INTO projects (id, title, created_at, updated_at, public_read_only) "
                    "VALUES (:id, 'Миграция', :now, :now, false)"
                ),
                {"id": project_id, "now": NOW},
            )
            for source_id, kind, content in (
                (text_id, "text", "Инженер готовит заявку."),
                (answer_id, "answer", "Да, диспетчер."),
            ):
                await connection.execute(
                    text(
                        "INSERT INTO sources (id, project_id, kind, title, content, status, "
                        "active, created_at) VALUES (:id, :project, :kind, :title, :content, "
                        "'ready', true, :now)"
                    ),
                    {
                        "id": source_id,
                        "project": project_id,
                        "kind": kind,
                        "title": kind,
                        "content": content,
                        "now": NOW,
                    },
                )
        legacy = [
            Source(
                id=source_id,
                project_id=project_id,
                kind=SourceKind(kind),
                title=kind,
                content=content,
                status=SourceStatus.READY,
                active=True,
                created_at=NOW,
            )
            for source_id, kind, content in (
                (text_id, "text", "Инженер готовит заявку."),
                (answer_id, "answer", "Да, диспетчер."),
            )
        ]
        saved_hash = _legacy_snapshot_hash(legacy)

        async with engine.begin() as connection:
            await connection.run_sync(migrate("head"))

        from sqlalchemy.ext.asyncio import async_sessionmaker  # noqa: PLC0415

        store = SqlStore(async_sessionmaker(engine, expire_on_commit=False))
        sources = await store.repositories().sources.list_by_project(project_id)
        by_id = {s.id: s for s in sources}
        assert by_id[text_id].origin is SourceOrigin.USER
        assert by_id[answer_id].origin is SourceOrigin.ANSWER
        assert all(s.trust is SourceTrust.PRIMARY for s in sources)
        assert all(s.parent_id is None and s.derivation is None for s in sources)
        assert not any(s.edited_by_human for s in sources)
        # Прогон, запущенный до миграции, восстанавливается: хеш снимка не изменился.
        assert source_snapshot_hash(sources) == saved_hash
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


async def test_postgres_parent_same_project_cascade_and_roundtrip() -> None:
    from tests.test_persistence import sql_test_store  # noqa: PLC0415

    async with sql_test_store() as (store, _sessions):
        repos = store.repositories()
        projects = []
        for title in ("Первый", "Второй"):
            project = Project(
                id=uuid4(), title=title, description=None, created_at=NOW, updated_at=NOW
            )
            await repos.projects.add(project)
            projects.append(project)
        parent = _source("встреча.mp4", kind=SourceKind.FILE, project_id=projects[0].id)
        await repos.sources.add(parent)
        child = _source(
            "Расшифровка",
            content="[00:00] Реплика.",
            project_id=projects[0].id,
            parent_id=parent.id,
            trust=SourceTrust.EXTRACTED,
            origin=SourceOrigin.DERIVED,
        )
        child.derivation = SourceDerivation(
            capability=SPEECH_TO_TEXT,
            provider="deepgram",
            model="nova-3",
            params={"segment_sec": 600},
            created_at=NOW,
        )
        await repos.sources.add(child)
        assert await repos.sources.get(child.id) == child

        assert await repos.sources.patch(child.id, {"edited_by_human": True})
        stored = await repos.sources.get(child.id)
        assert stored is not None
        assert stored.edited_by_human is True

        foreign = _source(
            "Чужой потомок",
            content="x",
            project_id=projects[1].id,
            parent_id=parent.id,
            origin=SourceOrigin.DERIVED,
        )
        with pytest.raises(IntegrityError):
            await repos.sources.add(foreign)

        stats = await repos.projects.stats([projects[0].id])
        assert stats[projects[0].id].sources == 1  # производные не считаются материалами

        await repos.sources.delete(parent.id)
        assert await repos.sources.get(child.id) is None


# ---------- обработка записи: удаление, рестарт, семафор ----------


async def _start(service: SourceService, project: Project) -> tuple[Source, Source]:
    """Запись принята, но фоновая обработка ещё не запускалась (оба узла `processing`)."""
    parent = await service.create_media(
        project.id, file_name="демо.mp4", mime="video/mp4", read=_reader(b"\x00" * 2048), title=None
    )
    sources = await service._repos.sources.list_by_project(project.id)
    return parent, next(s for s in sources if s.parent_id == parent.id)


async def test_transcript_cannot_be_deleted_while_processing(tmp_path: Path) -> None:
    stt = _CountingStt()
    service, store, project = await _service(tmp_path, stt=stt)
    parent, child = await _start(service, project)
    with pytest.raises(ConflictError, match="ещё обрабатывается"):
        await service.delete(child.id)
    await service.process_file(parent.id)
    assert store.sources[child.id].status is SourceStatus.READY
    assert stt.calls == 2  # два сегмента, распознаны один раз
    await service.delete(child.id)  # после обработки — можно
    assert child.id not in store.sources
    assert parent.id in store.sources


async def test_missing_transcript_skips_stt_and_fails_record(tmp_path: Path) -> None:
    stt = _CountingStt()
    service, store, project = await _service(tmp_path, stt=stt)
    parent, child = await _start(service, project)
    del store.sources[child.id]  # расшифровки нет (например, удалена в обход сервиса)
    await service.process_file(parent.id)
    assert stt.calls == 0
    assert store.sources[parent.id].status is SourceStatus.FAILED
    assert store.sources[parent.id].error == TRANSCRIPT_MISSING


async def test_deleting_record_while_processing_does_not_resurrect(tmp_path: Path) -> None:
    service, store, project = await _service(tmp_path)
    parent, child = await _start(service, project)
    await service.delete(parent.id)
    await service.process_file(parent.id)  # фоновая задача стартовала после удаления
    assert parent.id not in store.sources
    assert child.id not in store.sources


async def test_restart_during_processing_fails_both_and_counts_once(tmp_path: Path) -> None:
    service, store, project = await _service(tmp_path)
    await _start(service, project)
    repos = store.repositories()
    assert await repos.sources.fail_processing("Разбор файла прервался") == 2
    sources = await repos.sources.list_by_project(project.id)
    assert {s.status for s in sources} == {SourceStatus.FAILED}
    context = build_run_context(project=project, sources=sources, questions=[], versions=[])
    assert context.analysis_input_complete is False
    assert any("без готового текста: 1." in w for w in context.warnings)


def test_record_failure_counts_when_all_derived_are_off() -> None:
    record = _source("встреча.mp4", kind=SourceKind.FILE, status=SourceStatus.FAILED)
    transcript = _source(
        "Расшифровка",
        parent_id=record.id,
        origin=SourceOrigin.DERIVED,
        trust=SourceTrust.EXTRACTED,
        status=SourceStatus.FAILED,
    )
    transcript.active = False
    context = build_run_context(
        project=_project(), sources=[record, transcript], questions=[], versions=[]
    )
    assert context.analysis_input_complete is False
    assert any("без готового текста: 1." in w for w in context.warnings)


class _Tracked(_Runner):
    """Считает одновременные ffprobe/ffmpeg: всё должно идти под семафором медиа."""

    def __init__(self) -> None:
        super().__init__(MediaProbe(duration_sec=10, has_audio=True))
        self.active = 0
        self.peak = 0

    async def _busy(self) -> None:
        self.active += 1
        self.peak = max(self.peak, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1

    async def probe(self, source: Path) -> MediaProbe:
        await self._busy()
        return await super().probe(source)

    async def segment(self, source: Path, out_dir: Path, *, segment_sec: int) -> list[Path]:
        await self._busy()
        return await super().segment(source, out_dir, segment_sec=segment_sec)


async def test_probe_runs_under_media_semaphore(tmp_path: Path) -> None:
    runner = _Tracked()
    media = MediaTranscriber(MockSpeechToText(delay_sec=0), runner, max_concurrent_jobs=1)
    file = tmp_path / "a.mp3"
    await asyncio.to_thread(file.write_bytes, b"x")
    jobs = [MediaJob(), MediaJob(), MediaJob()]
    await asyncio.gather(*(media.transcribe(file, job=job) for job in jobs))
    assert runner.peak == 1
    assert all(job.probe is not None for job in jobs)


async def test_assistant_context_skips_record_without_text(tmp_path: Path) -> None:
    service, store, project = await _service(tmp_path)
    await _upload(service, project)
    assistant = AssistantService(store.repositories(), resolver=None)  # type: ignore[arg-type]
    captured: dict[str, Any] = {}

    async def fake(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "ok"

    assistant._reply_with_context = fake  # type: ignore[method-assign]
    await assistant.reply(project.id, message="Что в записи?", diagram_xml="", history=[])
    assert [item["title"] for item in captured["sources"]] == ["Расшифровка: демо.mp4"]


# ---------- PostgreSQL: полный цикл, откат 0016 ----------


async def test_postgres_media_cycle_persists_media_and_derivation(tmp_path: Path) -> None:
    from tests.test_persistence import sql_test_store  # noqa: PLC0415

    async with sql_test_store() as (store, _sessions):
        repos = store.repositories()
        project = Project(id=uuid4(), title="PG", description=None, created_at=NOW, updated_at=NOW)
        await repos.projects.add(project)
        service = _build(repos, tmp_path)
        parent, child = await _upload(service, project)
        assert parent.status is SourceStatus.READY
        assert parent.media is not None
        assert parent.media.has_video is True
        assert child.derivation is not None
        assert child.derivation.capability == SPEECH_TO_TEXT
        assert child.derivation.params["duration_sec"] == 900
        assert child.content.startswith("[00:00] ")
        # Рестарт во время обработки: оба узла failed.
        second, transcript = await _start(service, project)
        assert await repos.sources.fail_processing("прервано") == 2
        for item in (second, transcript):
            stored = await repos.sources.get(item.id)
            assert stored is not None
            assert stored.status is SourceStatus.FAILED


def _alembic(target: str, *, down: bool = False):
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))

    def run(sync_connection) -> None:
        config.attributes["connection"] = sync_connection
        (command.downgrade if down else command.upgrade)(config, target)

    return run


async def test_postgres_downgrade_0016_folds_transcript_back_into_record(tmp_path: Path) -> None:
    from tests.test_persistence import sql_test_store  # noqa: PLC0415

    async with sql_test_store() as (store, sessions):
        repos = store.repositories()
        project = Project(
            id=uuid4(), title="Откат", description=None, created_at=NOW, updated_at=NOW
        )
        await repos.projects.add(project)
        parent, child = await _upload(_build(repos, tmp_path), project)
        quote = child.content.split("\n")[0].removeprefix("[00:00] ")[:40]
        seed = build_seed().versions[0]
        version = replace(
            seed,
            id=uuid4(),
            project_id=project.id,
            run_id=None,
            number=1,
            trace={
                "Task_1": Quote(source_id=child.id, quote=quote),
                "Task_2": Quote(source_id=parent.id, quote="x"),
            },
        )
        await repos.versions.add(version)
        async with sessions.begin() as session:
            await session.execute(
                text(
                    "INSERT INTO questions (id, project_id, code, kind, severity, status, text, "
                    "assumption, created_at, updated_at, about, element_ids) VALUES (:id, :p, "
                    "'Q-1', 'missing_actor', 'major', 'open', 'Кто?', 'Диспетчер', :now, :now, "
                    "CAST(:about AS JSONB), CAST('[]' AS JSONB))"
                ),
                {
                    "id": uuid4(),
                    "p": project.id,
                    "now": NOW,
                    "about": json.dumps({"source_id": str(child.id), "quote": quote}),
                },
            )
            connection = await session.connection()
            await connection.run_sync(_alembic("0015_version_sessions", down=True))
            rows = (
                await session.execute(
                    text("SELECT id, content, status FROM sources WHERE project_id = :p"),
                    {"p": project.id},
                )
            ).all()
            about = await session.scalar(
                text("SELECT about FROM questions WHERE project_id = :p"), {"p": project.id}
            )
            trace = await session.scalar(
                text("SELECT trace FROM diagram_versions WHERE id = :v"), {"v": version.id}
            )
            await connection.run_sync(_alembic("head"))
        assert trace["Task_1"]["source_id"] == str(parent.id)
        assert trace["Task_2"] == {"source_id": str(parent.id), "quote": "x"}
        assert [(row.id, row.status) for row in rows] == [(parent.id, "ready")]
        assert rows[0].content == child.content  # текст расшифровки вернулся в запись
        assert about["source_id"] == str(parent.id)  # цитата не повисла


async def test_postgres_downgrade_0016_refuses_unfoldable_derived() -> None:
    from tests.test_persistence import sql_test_store  # noqa: PLC0415

    async with sql_test_store() as (store, sessions):
        repos = store.repositories()
        project = Project(
            id=uuid4(), title="Отказ", description=None, created_at=NOW, updated_at=NOW
        )
        await repos.projects.add(project)
        record = _source("скан.pdf", kind=SourceKind.FILE, project_id=project.id, content="x")
        await repos.sources.add(record)
        ocr = _source(
            "OCR",
            content="Текст страницы",
            project_id=project.id,
            parent_id=record.id,
            origin=SourceOrigin.DERIVED,
            trust=SourceTrust.EXTRACTED,
        )
        ocr.derivation = SourceDerivation(capability="ocr", provider="mock", created_at=NOW)
        await repos.sources.add(ocr)
        async with sessions() as session:
            connection = await session.connection()
            with pytest.raises(RuntimeError, match="Откат 0016 потерял бы"):
                await connection.run_sync(_alembic("0015_version_sessions", down=True))
            await session.rollback()
        assert await repos.sources.get(ocr.id) is not None
