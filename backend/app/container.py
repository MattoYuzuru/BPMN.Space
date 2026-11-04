"""Сборка приложения: выбирает persistent или тестовые реализации портов."""

import asyncio
from dataclasses import dataclass, replace

import httpx

from app.config import Settings
from app.domain.credentials import LlmCredential
from app.domain.models import RunStage
from app.fixtures import read_bpmn
from app.fixtures.examples import EXAMPLES
from app.fixtures.playbook import PLAYBOOK
from app.fixtures.samples import SAMPLES
from app.infra.bpmn_tools import HttpBpmnTools, MockBpmnTools
from app.infra.crypto import CredentialCipher
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
from app.llm.client import LlmClient, LlmConfig
from app.llm.factory import build_client, build_pipeline, call_knobs
from app.llm.mock import MockPipeline
from app.llm.pipeline import LlmPipeline
from app.services.access import AccessService
from app.services.assistant import AssistantService
from app.services.catalog import ExampleService, TranscriptionService
from app.services.collaboration import RealtimeHub
from app.services.common import Runtime
from app.services.llm_credentials import LlmCredentialService
from app.services.model_resolver import ModelResolver
from app.services.onboarding import OnboardingService
from app.services.projects import ProjectService
from app.services.questions import QuestionService
from app.services.runs import RunService
from app.services.samples import SampleService
from app.services.sharing import SharingService
from app.services.sources import SourceService
from app.services.versions import VersionService


def _server_pipeline(settings: Settings, transport: httpx.AsyncBaseTransport | None):
    """Модель оператора из `LLM_*` — запасной путь для пользователей без своего ключа."""
    provider = settings.llm_provider.lower()
    if provider == "mock":
        return MockPipeline(playbook=PLAYBOOK, read_bpmn=read_bpmn)
    if provider not in {"openai_compatible", "deepseek", "anthropic", "openai"}:
        raise ValueError(f"Неизвестный LLM_PROVIDER: {provider}")
    api_key, base_url, model = settings.llm_connection()
    knobs = call_knobs(settings)
    thinking = settings.llm_runtime(warn=True)["thinking"]
    config = LlmConfig(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        thinking=thinking,  # type: ignore[arg-type]
        **{k: v for k, v in knobs.items()},  # type: ignore[arg-type]
    )
    return build_pipeline(config, settings, transport=transport)


def _mock_pace(settings: Settings):
    async def pace(stage: RunStage) -> None:
        # Вызывается только для mock-пайплайна: реальный прогон не ждёт анимацию UI.
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
                settings.deepgram_api_key.get_secret_value(),
                timeout_sec=settings.deepgram_timeout_sec,
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
    assistant: AssistantService
    llm_credentials: LlmCredentialService
    access: AccessService
    sharing: SharingService
    onboarding: OnboardingService
    samples: SampleService
    realtime: RealtimeHub


def build_container(
    settings: Settings,
    *,
    runtime: Runtime | None = None,
    database: Database | None = None,
    llm_transport: httpx.AsyncBaseTransport | None = None,
) -> Container:
    """`database` — готовое подключение (тесты со своей схемой PostgreSQL), `llm_transport` —
    подмена HTTP к провайдерам моделей (тесты без сети)."""
    runtime = runtime or Runtime()
    settings.validate_for_runtime()

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
    bpmn_tools = build_bpmn_tools(settings)
    server_pipeline = _server_pipeline(settings, llm_transport)
    cipher = CredentialCipher(
        settings.credentials_encryption_key, allow_ephemeral=not settings.is_production
    )

    def user_pipeline(config: LlmConfig, _credential: LlmCredential) -> LlmPipeline:
        return build_pipeline(
            replace(config, **call_knobs(settings)),  # type: ignore[arg-type]
            settings,
            user_supplied=True,
            transport=llm_transport,
        )

    def validation_client(config: LlmConfig) -> LlmClient:
        return build_client(
            replace(config, **call_knobs(settings)),  # type: ignore[arg-type]
            user_supplied_url=True,
            allowed_private_hosts=settings.llm_allowed_private_hosts,
            transport=llm_transport,
        )

    resolver = ModelResolver(
        repos,
        server_pipeline=server_pipeline,
        cipher=cipher,
        factory=user_pipeline,
        runtime=runtime,
        production=settings.is_production,
        server_max_effort=settings.llm_server_max_effort,
    )

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
            resolver=resolver,
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
            session_idle_sec=settings.version_session_idle_sec,
            session_max_sec=settings.version_session_max_sec,
        ),
        examples=ExampleService(EXAMPLES),
        transcriptions=TranscriptionService(stt, max_audio_bytes=settings.max_audio_bytes),
        assistant=AssistantService(repos, resolver=resolver),
        llm_credentials=LlmCredentialService(
            repos,
            cipher=cipher,
            client_factory=validation_client,
            runtime=runtime,
            allowed_private_hosts=tuple(settings.llm_allowed_private_hosts),
            models_cache_sec=settings.llm_models_cache_sec,
            anthropic_effort=settings.anthropic_effort_default(),
        ),
        access=access,
        sharing=SharingService(access, runtime=runtime),
        onboarding=onboarding,
        samples=SampleService(sources, samples=SAMPLES),
        realtime=realtime,
    )
