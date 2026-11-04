"""Паузы демо не должны попадать в реальные прогоны и разбор источников."""

from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.container import _mock_pace, build_container
from app.domain.analysis import AnalysisResult, RunContext
from app.domain.models import RunMode, RunStage, SourceKind


class _FakePipeline:
    model_name = "fake"

    def __init__(self, provider: str) -> None:
        self.provider = provider

    async def aclose(self) -> None:
        return None

    async def analyze(self, context: RunContext) -> AnalysisResult:
        return AnalysisResult()


@pytest.mark.parametrize(
    ("provider", "paced"), [("openai_compatible", False), ("anthropic", False), ("mock", True)]
)
async def test_only_mock_pipeline_waits_for_demo_pace(provider: str, paced: bool) -> None:
    container = build_container(Settings(mock_delay_scale=0, seed_demo_data=False))
    pace = AsyncMock()
    container.runs._pace = pace
    container.runs._pipeline = _FakePipeline(provider)
    project = (await container.projects.create(title="П", description=None)).project
    await container.sources.create_text(
        project.id, content="Текст.", title="Т", kind=SourceKind.TEXT, duration_sec=None
    )
    await container.runs.start(project.id, mode=RunMode.ANALYZE, created_by=None)
    await container.spawner.wait_idle()
    assert bool(pace.await_count) is paced


async def test_mock_demo_pace_remains_configurable(monkeypatch) -> None:
    sleep = AsyncMock()
    monkeypatch.setattr("app.container.asyncio.sleep", sleep)
    await _mock_pace(Settings(llm_provider="mock"))(RunStage.EXTRACTING)
    sleep.assert_awaited_once_with(2.4)


@pytest.mark.parametrize(("provider", "delay"), [("mock", 1.5), ("openai_compatible", 0)])
def test_real_document_parser_has_no_demo_delay(provider, delay) -> None:
    settings = Settings(
        database_url=None,
        seed_demo_data=False,
        llm_provider=provider,
        llm_api_key="test-only",
        llm_model="test-model",
        llm_base_url="https://llm.example.test/v1",
        mock_delay_scale=1,
    )
    assert build_container(settings).sources._parse_delay == delay
