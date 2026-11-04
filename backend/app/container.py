"""Сборка приложения: выбирает persistent или тестовые реализации портов."""

import asyncio
from dataclasses import dataclass

from app.config import Settings
from app.domain.models import RunStage
from app.fixtures import read_bpmn
from app.fixtures.examples import EXAMPLES
from app.fixtures.playbook import PLAYBOOK
from app.fixtures.samples import SAMPLES
from app.infra.bpmn_tools import HttpBpmnTools, MockBpmnTools
from app.infra.database import Database
from app.infra.events import InMemoryRunEventBus
from app.infra.repositories.base import Repositories
from app.infra.repositories.memory import InMemoryStore
from app.infra.seed import build_seed
from app.infra.storage import InMemoryFileStorage, LocalFileStorage
from app.infra.tasks import AsyncioTaskSpawner
from app.ingest.context import configure_llm_limits
from app.ingest.deepgram import DeepgramSpeechToText
from app.ingest.media import FfmpegRunner, MediaTranscriber
from app.ingest.parsers import LocalDocumentParser
from app.ingest.stt import MockSpeechToText, SpeechToText
from app.llm.deepseek import OpenAICompatiblePipeline
from app.llm.mock import MockPipeline
from app.services.access import AccessService
from app.services.assistant import AssistantModel, AssistantService
from app.services.catalog import ExampleService, TranscriptionService
from app.services.collaboration import RealtimeHub
from app.services.common import Runtime
from app.services.onboarding import OnboardingService
from app.services.projects import ProjectService
from app.services.questions import QuestionService
from app.services.runs import RunService
from app.services.samples import SampleService
from app.services.sharing import SharingService
from app.services.sources import SourceService
from app.services.versions import VersionService


def _mock_pace(settings: Settings):
    async def pace(stage: RunStage) -> None:
        # Задержки нужны только для демонстрации mock; реальный прогон не ждёт анимацию UI.
        if settings.llm_provider.lower() != "mock":
            return
        delay = settings.mock_delay(settings.mock_stage_delays.get(stage.value, 0.0))
        if delay:
            await asyncio.sleep(delay)

    return pace


def build_bpmn_tools(settings: Settings):
    if settings.bpmn_tools_url:
        return HttpBpmnTools(
            settings.bpmn_tools_url,
            timeout_sec=settings.bpmn_tools_timeout_sec,
            max_bytes=settings.max_diagram_bytes,
        )
    if settings.app_env.lower() in {"prod", "production"}:
        raise ValueError("Production требует BPMN_TOOLS_URL для настоящей проверки схем")
    return MockBpmnTools()


def build_stt(settings: Settings) -> SpeechToText:
    match settings.stt_provider.lower():
        case "mock":
            return MockSpeechToText(
                delay_sec=settings.mock_delay(settings.mock_transcription_delay_sec)
            )
        case "deepgram":
            if not settings.deepgram_api_key:
                raise ValueError("STT_PROVIDER=deepgram требует DEEPGRAM_API_KEY в .env")
            return DeepgramSpeechToText(
                settings.deepgram_api_key, timeout_sec=settings.deepgram_timeout_sec
            )
        case provider:
            raise ValueError(f"Неизвестный STT_PROVIDER: {provider}")


def build_media_transcriber(settings: Settings, stt: SpeechToText) -> MediaTranscriber:
    return MediaTranscriber(
        stt,
        FfmpegRunner(
            ffmpeg=settings.ffmpeg_path,
            ffprobe=settings.ffprobe_path,
            timeout_sec=settings.media_ffmpeg_timeout_sec,
        ),
        segment_sec=settings.media_segment_sec,
        parallel_segments=settings.stt_parallel_segments,
        max_duration_sec=settings.media_max_duration_sec,
        timeout_base_sec=settings.stt_segment_timeout_base_sec,
        timeout_per_audio_sec=settings.stt_segment_timeout_per_audio_sec,
        max_concurrent_jobs=settings.media_max_concurrent_jobs,
        raw_fallback=settings.stt_provider.lower() == "mock",
    )


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
    realtime: RealtimeHub


def build_container(
    settings: Settings, *, runtime: Runtime | None = None, database: Database | None = None
) -> Container:
    """`database` позволяет подставить готовое подключение (тесты со своей схемой PostgreSQL)."""
    runtime = runtime or Runtime()

    if database is None and settings.database_url:
        database = Database(
            settings.database_url,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_timeout=settings.database_pool_timeout_sec,
        )
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
    realtime = RealtimeHub()
    spawner = AsyncioTaskSpawner()
    assistant_model: AssistantModel | None = None
    bpmn_tools = build_bpmn_tools(settings)
    match settings.llm_provider.lower():
        case "mock":
            pipeline = MockPipeline(playbook=PLAYBOOK, read_bpmn=read_bpmn)
        case "openai_compatible" | "deepseek":
            api_key, base_url, model = settings.llm_connection()
            retries = settings.llm_max_retries
            retry_base = settings.llm_retry_base_sec
            retry_max = settings.llm_retry_max_sec
            timeout = settings.llm_timeout_sec
            thinking: bool | None = None
            if settings.llm_provider.lower() == "deepseek":
                thinking = settings.deepseek_thinking_enabled
                retries = settings.deepseek_max_retries
                retry_base = settings.deepseek_retry_base_sec
                retry_max = settings.deepseek_retry_max_sec
                timeout = settings.deepseek_timeout_sec
            pipeline = OpenAICompatiblePipeline(
                api_key=api_key,
                base_url=base_url,
                model=model,
                timeout_sec=timeout,
                json_mode=settings.llm_json_mode,
                semantic_review=settings.llm_semantic_review,
                json_max_tokens=settings.llm_json_max_tokens,
                max_retries=retries,
                retry_base_sec=retry_base,
                retry_max_sec=retry_max,
                thinking=thinking,
                json_temperature=settings.llm_json_temperature,
            )
            assistant_model = pipeline
        case provider:
            raise ValueError(f"Неизвестный LLM_PROVIDER: {provider}")

    stt = build_stt(settings)

    onboarding = OnboardingService(
        repos,
        runtime=runtime,
        enabled=settings.auth_enabled and settings.onboarding_enabled,
    )
    configure_llm_limits(
        parallel_requests=settings.llm_parallel_requests, chunk_chars=settings.llm_chunk_chars
    )
    media = build_media_transcriber(settings, stt)
    sources = SourceService(
        repos,
        parser=LocalDocumentParser(
            max_text_chars=settings.max_text_chars,
            max_pdf_chars=settings.max_text_chars,
            max_pdf_pages=settings.max_pdf_pages,
            max_sheet_rows=settings.max_sheet_rows,
            timeout_sec=settings.parse_timeout_sec,
        ),
        media=media,
        max_media_bytes=settings.max_media_bytes,
        storage=storage,
        runtime=runtime,
        max_text_chars=settings.max_text_chars,
        max_upload_bytes=settings.max_upload_bytes,
        parse_delay_sec=(
            settings.mock_delay(settings.mock_parse_delay_sec)
            if settings.llm_provider.lower() == "mock"
            else 0.0
        ),
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
            pace=_mock_pace(settings),
            context_budget_chars=settings.context_budget_chars(),
            deadline_sec=settings.run_deadline_sec,
            deadline_for=settings.run_deadline,
            progress=onboarding,
            broadcast=realtime.publish,
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
        realtime=realtime,
    )
