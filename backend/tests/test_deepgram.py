"""Адаптер Deepgram (RFC-0006): запрос, таймкоды и классы ошибок без текста провайдера."""

import httpx
import pytest

from app.domain.capabilities import CapabilityError, ErrorClass
from app.ingest.adapters.stt_deepgram import DeepgramSttAdapter
from app.ingest.stt import NoSpeechError

_SECRET = "dg-test-only-key"  # noqa: S105


def _adapter(handler) -> DeepgramSttAdapter:
    return DeepgramSttAdapter(_SECRET, transport=httpx.MockTransport(handler))


async def test_transcription_uses_deepgram_auth_and_returns_russian_transcript() -> None:
    payload = {
        "metadata": {"duration": 4.25},
        "results": {"channels": [{"alternatives": [{"transcript": "Проверить заявку."}]}]},
    }
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json=payload)

    adapter = _adapter(handler)
    transcript = await adapter.transcribe(b"audio", mime="audio/webm")
    await adapter.aclose()

    assert transcript.text == "Проверить заявку."
    assert transcript.duration_sec == 4.25
    assert transcript.language == "ru-RU"
    assert transcript.provider == "deepgram"
    assert transcript.model == "nova-3"
    request = sent[0]
    assert request.url.host == "api.deepgram.com"
    assert request.url.path == "/v1/listen"
    assert request.headers["Authorization"] == f"Token {_SECRET}"
    assert request.headers["Content-Type"] == "audio/webm"
    assert request.url.params["model"] == "nova-3"
    assert request.url.params["utterances"] == "true"


async def test_utterances_are_returned_for_timecodes() -> None:
    payload = {
        "metadata": {"duration": 12.0},
        "results": {
            "channels": [{"alternatives": [{"transcript": "Раз. Два."}]}],
            "utterances": [
                {"start": 0.5, "transcript": "Раз."},
                {"start": 5.0, "transcript": "Два."},
            ],
        },
    }

    adapter = _adapter(lambda _request: httpx.Response(200, json=payload))
    transcript = await adapter.transcribe(b"audio", mime="audio/ogg")
    await adapter.aclose()

    assert [(item.start_sec, item.text) for item in transcript.utterances] == [
        (0.5, "Раз."),
        (5.0, "Два."),
    ]


async def test_silence_is_a_recognition_result_not_a_provider_failure() -> None:
    payload = {
        "metadata": {"duration": 2.0},
        "results": {"channels": [{"alternatives": [{"transcript": "  "}]}]},
    }
    adapter = _adapter(lambda _request: httpx.Response(200, json=payload))
    with pytest.raises(NoSpeechError):
        await adapter.transcribe(b"audio", mime="audio/webm")
    await adapter.aclose()


async def test_invalid_transcript_is_transient_not_speech() -> None:
    payload = {
        "metadata": {"duration": 2.0},
        "results": {"channels": [{"alternatives": [{"transcript": None}]}]},
    }
    adapter = _adapter(lambda _request: httpx.Response(200, json=payload))
    with pytest.raises(CapabilityError) as info:
        await adapter.transcribe(b"audio", mime="audio/webm")
    assert info.value.error_class is ErrorClass.TRANSIENT
    await adapter.aclose()


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, ErrorClass.AUTH),
        (403, ErrorClass.AUTH),
        (402, ErrorClass.QUOTA_EXHAUSTED),
        (413, ErrorClass.UNSUPPORTED),
        (429, ErrorClass.TRANSIENT),
        (500, ErrorClass.TRANSIENT),
        (400, ErrorClass.FATAL),
    ],
)
async def test_http_errors_are_classified_without_provider_text(
    status: int, expected: ErrorClass
) -> None:
    secret_body = "provider detail with key sk-live-0123456789"  # noqa: S105

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=secret_body)

    adapter = _adapter(handler)
    with pytest.raises(CapabilityError) as info:
        await adapter.transcribe(b"audio", mime="audio/webm")
    assert info.value.error_class is expected
    assert "sk-live" not in info.value.message
    await adapter.aclose()


async def test_quota_marker_in_429_body_is_quota_exhausted() -> None:
    adapter = _adapter(
        lambda _request: httpx.Response(429, json={"error": {"code": "insufficient_quota"}})
    )
    with pytest.raises(CapabilityError) as info:
        await adapter.transcribe(b"audio", mime="audio/webm")
    assert info.value.error_class is ErrorClass.QUOTA_EXHAUSTED
    await adapter.aclose()


async def test_check_uses_cheap_token_endpoint() -> None:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"access_token": "x"})

    adapter = _adapter(handler)
    detail = await adapter.check()
    await adapter.aclose()

    assert "действует" in detail
    assert sent[0].url.path == "/v1/auth/token"
    assert sent[0].headers["Authorization"] == f"Token {_SECRET}"
