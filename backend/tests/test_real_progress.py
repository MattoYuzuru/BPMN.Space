"""Паузы демо не должны попадать в реальные прогоны и разбор источников."""

from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.container import _mock_pace, build_container
from app.domain.models import RunStage


@pytest.mark.parametrize("provider", ["deepseek", "openai_compatible"])
async def test_real_provider_never_waits_for_demo_pace(provider, monkeypatch) -> None:
    sleep = AsyncMock()
    monkeypatch.setattr("app.container.asyncio.sleep", sleep)
    settings = Settings(llm_provider=provider, mock_delay_scale=1)
    for stage in RunStage:
        await _mock_pace(settings)(stage)
    sleep.assert_not_awaited()


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
