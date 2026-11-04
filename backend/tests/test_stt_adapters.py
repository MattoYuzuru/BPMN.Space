"""STT-адаптеры: отказ SSRF-проверки не должен превращаться в 500 (ревью волны 2).

`UnsafeBaseUrlError` (ValueError) приходит из закреплённого транспорта уже во время запроса,
а не только при разборе адреса. Адаптер обязан вернуть `CapabilityError(unsupported)`: тогда
сохранение ключа отвечает 422, а маршрутизатор пробует следующий ключ или сервер.
"""

import pytest

from app.domain.capabilities import CapabilityError, ErrorClass
from app.ingest.adapters.stt_openai import OpenAISttAdapter

API_KEY = "sk-stt-test-0123456789"


def _guarded_factory(*_args: object, **_kwargs: object):
    raise ValueError("Адрес провайдера указывает на закрытую сеть")


def test_ssrf_rejection_is_unsupported_capability_error() -> None:
    with pytest.raises(CapabilityError) as info:
        OpenAISttAdapter(
            "openai_compatible",
            API_KEY,
            base_url="https://127.0.0.1/v1",
            client_factory=_guarded_factory,
        )
    assert info.value.error_class is ErrorClass.UNSUPPORTED
    assert "безопасност" in info.value.message
    assert API_KEY not in info.value.message
