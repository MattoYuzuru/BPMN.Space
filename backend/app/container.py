"""Сборка приложения: выбирает persistent или тестовые реализации портов."""

import asyncio
from dataclasses import dataclass

from app.config import Settings
from app.domain.analysis import MAX_SOURCE_TEXT_CHARS
from app.domain.models import RunStage
from app.fixtures import read_bpmn
from app.fixtures.examples import EXAMPLES
from app.fixtures.playbook import PLAYBOOK
from app.fixtures.samples import SAMPLES
from app.infra.bpmn_tools import MockBpmnTools
from app.infra.database import Database
from app.infra.events import InMemoryRunEventBus
from app.infra.repositories.base import Repositories
from app.infra.repositories.memory import InMemoryStore
from app.infra.seed import build_seed
from app.infra.storage import InMemoryFileStorage, LocalFileStorage
from app.infra.tasks import AsyncioTaskSpawner
from app.ingest.deepgram import DeepgramSpeechToText
from app.ingest.parsers import LocalDocumentParser
from app.ingest.stt import MockSpeechToText
from app.llm.deepseek import DeepSeekPipeline
from app.llm.mock import MockPipeline
from app.services.access import AccessService
from app.services.assistant import AssistantModel, AssistantService
from app.services.catalog import ExampleService, TranscriptionService
from app.services.common import Runtime
from app.services.onboarding import OnboardingService
from app.services.projects import ProjectService
from app.services.questions import QuestionService
from app.services.runs import RunService
from app.services.samples import SampleService
from app.services.sharing import SharingService
from app.services.sources import SourceService
from app.services.versions import VersionService


@dataclass(frozen=True, slots=True)
class Container:
    settings: Settings
    repos: Repositories
    database: Database | None
    storage: InMemoryFileStorage | LocalFileStorage
    spawner: AsyncioTaskSpawner
    projects: ProjectService
    sources: SourceService
    questions: QuestionService
    runs: RunService
    versions: VersionService
    examples: ExampleService
    transcriptions: TranscriptionService
    assistant: AssistantService | None
    access: AccessService
    sharing: SharingService
    onboarding: OnboardingService
    samples: SampleService


def build_container(
    settings: Settings, *, runtime: Runtime | None = None, database: Database | None = None
) -> Container:
    """`database` позволяет подставить готовое подключение (тесты со своей схемой PostgreSQL)."""
    runtime = runtime or Runtime()

    if database is None and settings.database_url:
        database = Database(settings.database_url)
    if database:
        repos = database.store.repositories()
        storage = LocalFileStorage(settings.upload_dir)
    else:
        store = InMemoryStore()
        if settings.seed_demo_data:
            seed = build_seed()
            store.load(
                projects=seed.projects,
                sources=seed.sources,
                questions=seed.questions,
                runs=seed.runs,
                versions=seed.versions,
            )
        repos = store.repositories()
        storage = InMemoryFileStorage()
    access = AccessService(repos.access, runtime=runtime)
    spawner = AsyncioTaskSpawner()
    assistant_model: AssistantModel | None = None
    # TODO(real): #6 HTTP-клиент к bpmn-tools (раскладка и bpmnlint) вместо MockBpmnTools.
    bpmn_tools = MockBpmnTools()
    match settings.llm_provider.lower():
        case "mock":
            pipeline = MockPipeline(playbook=PLAYBOOK, read_bpmn=read_bpmn)
        case "deepseek":
            if not settings.deepseek_api_key:
                raise ValueError("LLM_PROVIDER=deepseek требует DEEPSEEK_API_KEY в .env")
            pipeline = DeepSeekPipeline(
                api_key=settings.deepseek_api_key,
                base_url=settings.deepseek_base_url,
                model=settings.deepseek_model,
                timeout_sec=settings.deepseek_timeout_sec,
                thinking_enabled=settings.deepseek_thinking_enabled,
                max_retries=settings.deepseek_max_retries,
                retry_base_sec=settings.deepseek_retry_base_sec,
                retry_max_sec=settings.deepseek_retry_max_sec,
            )
            assistant_model = pipeline
        case provider:
            raise ValueError(f"Неизвестный LLM_PROVIDER: {provider}")

    match settings.stt_provider.lower():
        case "mock":
            stt = MockSpeechToText(
                delay_sec=settings.mock_delay(settings.mock_transcription_delay_sec)
            )
        case "deepgram":
            if not settings.deepgram_api_key:
                raise ValueError("STT_PROVIDER=deepgram требует DEEPGRAM_API_KEY в .env")
            stt = DeepgramSpeechToText(settings.deepgram_api_key)
        case provider:
            raise ValueError(f"Неизвестный STT_PROVIDER: {provider}")

    async def mock_pace(stage: RunStage) -> None:
        # TODO(real): #5 задержки имитируют работу модели и действуют при любом LLM_PROVIDER,
        # в том числе с DeepSeek; убрать, когда mock перестанет быть основным демо-режимом.
        delay = settings.mock_delay(settings.mock_stage_delays.get(stage.value, 0.0))
        if delay:
            await asyncio.sleep(delay)

    onboarding = OnboardingService(
        repos,
        runtime=runtime,
        enabled=settings.auth_enabled and settings.onboarding_enabled,
    )
    sources = SourceService(
        repos,
        parser=LocalDocumentParser(
            max_text_chars=min(settings.max_text_chars, MAX_SOURCE_TEXT_CHARS),
            max_pdf_chars=settings.max_text_chars,
            max_pdf_pages=settings.max_pdf_pages,
            timeout_sec=settings.parse_timeout_sec,
        ),
        storage=storage,
        runtime=runtime,
        max_text_chars=settings.max_text_chars,
        max_upload_bytes=settings.max_upload_bytes,
        parse_delay_sec=settings.mock_delay(settings.mock_parse_delay_sec),
    )

    return Container(
        settings=settings,
        repos=repos,
        database=database,
        storage=storage,
        spawner=spawner,
        projects=ProjectService(repos, examples=EXAMPLES, runtime=runtime, storage=storage),
        sources=sources,
        questions=QuestionService(repos, runtime=runtime),
        runs=RunService(
            repos,
            pipeline=pipeline,
            bpmn_tools=bpmn_tools,
            events=InMemoryRunEventBus(),
            spawner=spawner,
            runtime=runtime,
            max_concurrent=settings.max_concurrent_runs,
            pace=mock_pace,
            context_budget_chars=settings.llm_context_budget_chars,
            deadline_sec=settings.run_deadline_sec,
            progress=onboarding,
        ),
        versions=VersionService(
            repos,
            bpmn_tools=bpmn_tools,
            runtime=runtime,
            max_diagram_bytes=settings.max_diagram_bytes,
        ),
        examples=ExampleService(EXAMPLES),
        transcriptions=TranscriptionService(stt, max_audio_bytes=settings.max_audio_bytes),
        assistant=(
            AssistantService(repos, model=assistant_model) if assistant_model is not None else None
        ),
        access=access,
        sharing=SharingService(access, runtime=runtime),
        onboarding=onboarding,
        samples=SampleService(sources, samples=SAMPLES),
    )
