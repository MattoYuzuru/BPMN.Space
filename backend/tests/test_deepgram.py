import json
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from app.ingest.deepgram import DeepgramSpeechToText


def test_deepgram_transcription_uses_server_auth_and_returns_russian_transcript() -> None:
    payload = {
        "metadata": {"duration": 4.25},
        "results": {"channels": [{"alternatives": [{"transcript": "Проверить заявку."}]}]},
    }
    with patch("app.ingest.deepgram.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(payload).encode()
        transcript = DeepgramSpeechToText("test-only")._transcribe_sync(b"audio", "audio/webm")
        request = urlopen.call_args.args[0]

    assert transcript.text == "Проверить заявку."
    assert transcript.duration_sec == 4.25
    assert transcript.language == "ru-RU"
    assert request.get_header("Authorization") == "Token test-only"
    assert parse_qs(urlsplit(request.full_url).query) == {
        "model": ["nova-3"],
        "language": ["ru"],
        "smart_format": ["true"],
    }
