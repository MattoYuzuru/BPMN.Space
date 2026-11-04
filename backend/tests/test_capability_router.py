"""Маршрутизация инструментов по ключам пользователя (RFC-0006, шаг 1).

Fake-адаптеры без сети: перебор по приоритету, классы ошибок, повторы, предохранитель,
пометки ключей (исчерпание, недействительность) и структурный результат отказа.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from app.domain.capabilities import (
    Capability,
    CapabilityError,
    CapabilityOutcome,
    CapabilityUnavailableError,
    CredentialKind,
    ErrorClass,
)
from app.domain.credentials import Credential
from app.infra.crypto import CredentialCipher
from app.infra.repositories.base import Repositories
from app.infra.repositories.memory import InMemoryStore
from app.ingest.adapters import AdapterContext, AdapterRegistry, AdapterSpec
from app.ingest.stt import Transcript
from app.services.capability_router import CapabilityRouter, RoutingPolicy
from app.services.common import Runtime

PLAIN_KEY = "sk-test-0123456789"
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


class _Clock:
    def __init__(self) -> None:
        self.now = NOW

    def monotonic(self) -> float:
        return 1000.0

    def __call__(self) -> datetime:
        return self.now


class _FakeAdapter:
    """Адаптер, который по плану отвечает расшифровкой или ошибкой класса."""

    capability = Capability.SPEECH_TO_TEXT
    provider = "fake"
    model: str | None = "fake-1"

    def __init__(self, context: AdapterContext, plan: dict[UUID, list[object]]) -> None:
        self.context = context
        self.credential_id = context.credential_id
        self._plan = plan
        self.calls = 0

    async def check(self) -> str:
        return "Ключ действует"

    async def transcribe(self, data: bytes, *, mime: str | None) -> Transcript:
        del data, mime
        self.calls += 1
        assert self.credential_id is not None
        script = self._plan.setdefault(self.credential_id, [])
        action = script.pop(0) if script else None
        if isinstance(action, CapabilityError):
            raise action
        if isinstance(action, float):
            await asyncio.sleep(action)  # медленный провайдер: проверка таймаута вызова
        return Transcript(
            text="расшифровано",
            duration_sec=1.0,
            provider="fake",
            model="fake-1",
            credential_id=self.credential_id,
        )

    async def aclose(self) -> None:
        return None


class _Harness:
    def __init__(
        self,
        *,
        attempts: int = 2,
        threshold: int = 3,
        request_timeout_sec: float = 120.0,
        run_deadline_sec: float = 600.0,
    ) -> None:
        self.clock = _Clock()
        store = InMemoryStore()
        self.repos: Repositories = store.repositories()
        self.cipher = CredentialCipher(
            SecretStr(Fernet.generate_key().decode()), allow_ephemeral=False
        )
        self.plan: dict[UUID, list[object]] = {}
        self.adapters: list[_FakeAdapter] = []

        def factory(context: AdapterContext) -> _FakeAdapter:
            adapter = _FakeAdapter(context, self.plan)
            self.adapters.append(adapter)
            return adapter

        self.registry = AdapterRegistry()
        self.registry.register(AdapterSpec(Capability.SPEECH_TO_TEXT, "fake", "Fake", factory))
        self.router = CapabilityRouter(
            self.repos,
            cipher=self.cipher,
            registry=self.registry,
            runtime=Runtime(clock=self.clock.__call__),
            policy=RoutingPolicy(
                max_attempts=attempts,
                retry_base_sec=0,
                retry_max_sec=0,
                breaker_threshold=threshold,
                breaker_cooldown_sec=60,
                quota_cooldown_sec=3600,
                request_timeout_sec=request_timeout_sec,
                run_deadline_sec=run_deadline_sec,
            ),
            monotonic=self.clock.monotonic,
            sleep=_no_sleep,
        )

    async def add(
        self,
        *,
        provider: str = "fake",
        priority: int = 100,
        enabled: bool = True,
        exhausted_until: datetime | None = None,
        kinds: tuple[CredentialKind, ...] = (CredentialKind.SPEECH_TO_TEXT,),
        label: str = "Ключ",
        user_id: UUID | None = None,
    ) -> Credential:
        owner = user_id or uuid4()
        credential = Credential(
            id=uuid4(),
            user_id=owner,
            provider=provider,
            label=label,
            encrypted_key=self.cipher.encrypt(owner, PLAIN_KEY),
            key_hint=PLAIN_KEY[-4:],
            kinds=kinds,
            priority=priority,
            enabled=enabled,
            exhausted_until=exhausted_until,
            created_at=NOW,
        )
        await self.repos.credentials.save(credential)  # type: ignore[union-attr]
        return credential

    async def run(self, *, user_id: UUID, progress=None):
        return await self.router.run(
            user_id=user_id,
            capability=Capability.SPEECH_TO_TEXT,
            invoke=lambda adapter: adapter.transcribe(b"audio", mime=None),
            progress=progress,
        )

    async def failure(self, coro) -> CapabilityOutcome:
        with pytest.raises(CapabilityUnavailableError) as info:
            await coro
        return info.value.outcome


async def _no_sleep(_seconds: float) -> None:
    return None


async def test_priority_order_and_first_working_key() -> None:
    harness = _Harness()
    user_id = uuid4()
    rejected = await harness.add(user_id=user_id, priority=50, label="Первый")
    harness.plan[rejected.id] = [CapabilityError(ErrorClass.AUTH, "отклонён")]
    working = await harness.add(user_id=user_id, priority=90, label="Второй")

    transcript = await harness.run(user_id=user_id)

    assert transcript.text == "расшифровано"
    # Меньший приоритет — раньше: отклонённый ключ 50 попробован до рабочего 90.
    assert harness.adapters[0].credential_id == rejected.id
    assert harness.adapters[1].credential_id == working.id
    stored = await harness.repos.credentials.get(rejected.id)  # type: ignore[union-attr]
    assert stored is not None
    # Отклонённый ключ помечен недействительным и выключен; следующий ключ работает.
    assert stored.last_error_code == "auth"
    assert stored.enabled is False


async def test_quota_is_not_retried_and_key_rests() -> None:
    harness = _Harness()
    user_id = uuid4()
    quota = await harness.add(user_id=user_id, priority=10)
    harness.plan[quota.id] = [
        CapabilityError(ErrorClass.QUOTA_EXHAUSTED, "кончилась квота", retry_after_sec=3600)
    ]
    spare = await harness.add(user_id=user_id, priority=20)

    await harness.run(user_id=user_id)

    first = next(item for item in harness.adapters if item.credential_id == quota.id)
    assert first.calls == 1  # без повтора на том же ключе
    assert any(item.credential_id == spare.id for item in harness.adapters)
    stored = await harness.repos.credentials.get(quota.id)  # type: ignore[union-attr]
    assert stored is not None
    assert stored.last_error_code == "quota_exhausted"
    assert stored.exhausted_until is not None
    # Долгий Retry-After не обрезается: ключ не тратит запросы, пока квота не вернётся.
    assert stored.exhausted_until == NOW + timedelta(seconds=3600)


async def test_transient_is_retried_then_next_key_is_used() -> None:
    harness = _Harness()
    user_id = uuid4()
    flaky = await harness.add(user_id=user_id, priority=10)
    harness.plan[flaky.id] = [
        CapabilityError(ErrorClass.TRANSIENT, "сбой"),
        CapabilityError(ErrorClass.TRANSIENT, "сбой"),
    ]
    await harness.add(user_id=user_id, priority=20)

    await harness.run(user_id=user_id)

    first = next(item for item in harness.adapters if item.credential_id == flaky.id)
    assert first.calls == 2  # повтор временного сбоя


async def test_unsupported_tries_another_provider() -> None:
    harness = _Harness()
    user_id = uuid4()
    broken = await harness.add(user_id=user_id, priority=10)
    harness.plan[broken.id] = [CapabilityError(ErrorClass.UNSUPPORTED, "формат не принят")]
    await harness.add(user_id=user_id, priority=20)

    await harness.run(user_id=user_id)

    stored = await harness.repos.credentials.get(broken.id)  # type: ignore[union-attr]
    assert stored is not None
    assert stored.last_error_code == "unsupported"
    assert stored.enabled is True  # ключ годен, просто не умеет этот материал


async def test_fatal_stops_routing_and_reports_failed() -> None:
    harness = _Harness()
    user_id = uuid4()
    fatal = await harness.add(user_id=user_id, priority=10)
    harness.plan[fatal.id] = [CapabilityError(ErrorClass.FATAL, "ошибка")]
    await harness.add(user_id=user_id, priority=20)

    outcome = await harness.failure(harness.run(user_id=user_id))

    assert outcome.status == "failed"
    assert outcome.reason == "fatal"
    assert len(harness.adapters) == 1  # следующий ключ уже не пробуем
    assert outcome.message


async def test_breaker_stops_repeat_calls_to_dead_key() -> None:
    harness = _Harness(threshold=2)
    user_id = uuid4()
    dead = await harness.add(user_id=user_id)
    harness.plan[dead.id] = [CapabilityError(ErrorClass.TRANSIENT, "сбой")] * 20

    first = await harness.failure(harness.run(user_id=user_id))
    second = await harness.failure(harness.run(user_id=user_id))
    calls_before = len(harness.adapters)
    third = await harness.failure(harness.run(user_id=user_id))

    assert first.reason == second.reason == "transient"
    assert len(harness.adapters) == calls_before  # предохранитель разомкнут: новых вызовов нет
    assert third.reason == "transient"
    assert third.attempts == 0
    del dead


async def test_missing_capability_reports_alternatives_for_available_keys() -> None:
    harness = _Harness()
    user_id = uuid4()
    # Ключа распознавания нет, зато есть ключ изображений: можно предложить кадры.
    await harness.add(
        user_id=user_id,
        provider="fake",
        kinds=(CredentialKind.VISION,),
    )
    harness.registry.register(
        AdapterSpec(Capability.VISION, "fake", "Fake", lambda context: _FakeAdapter(context, {}))
    )

    outcome = await harness.failure(harness.run(user_id=user_id))

    assert outcome.status == "unavailable"
    assert outcome.reason == "capability_missing"
    assert outcome.alternatives == ("vision:frames",)
    assert "Нет ключа" in (outcome.message or "")


async def test_exhausted_disabled_and_foreign_keys_are_skipped() -> None:
    harness = _Harness()
    user_id = uuid4()
    await harness.add(
        user_id=user_id,
        priority=10,
        exhausted_until=NOW + timedelta(minutes=5),
        label="Исчерпан",
    )
    await harness.add(user_id=user_id, priority=20, enabled=False, label="Выключен")
    working = await harness.add(user_id=user_id, priority=30, label="Рабочий")

    transcript = await harness.run(user_id=user_id)

    assert transcript.text == "расшифровано"
    assert [item.credential_id for item in harness.adapters] == [working.id]


async def test_fallback_operator_path_is_used_after_user_keys_fail() -> None:
    harness = _Harness()
    user_id = uuid4()
    broken = await harness.add(user_id=user_id)
    harness.plan[broken.id] = [CapabilityError(ErrorClass.AUTH, "отклонён")]

    async def fallback() -> Transcript:
        return Transcript(text="сервер", duration_sec=2, provider="server")

    value = await harness.router.run(
        user_id=user_id,
        capability=Capability.SPEECH_TO_TEXT,
        invoke=lambda adapter: adapter.transcribe(b"audio", mime=None),
        fallback=fallback,
    )

    assert value.text == "сервер"


async def test_fallback_failure_is_reported_with_structural_progress() -> None:
    harness = _Harness()
    user_id = uuid4()
    broken = await harness.add(user_id=user_id)
    harness.plan[broken.id] = [CapabilityError(ErrorClass.AUTH, "отклонён")]

    async def fallback() -> Transcript:
        raise CapabilityError(ErrorClass.TRANSIENT, "сервер недоступен")

    outcome = await harness.failure(
        harness.router.run(
            user_id=user_id,
            capability=Capability.SPEECH_TO_TEXT,
            invoke=lambda adapter: adapter.transcribe(b"audio", mime=None),
            fallback=fallback,
            progress=lambda: ("00:00–00:10", "00:10–01:00"),
        )
    )

    assert outcome.status == "unavailable"
    # Причина — класс отказа ключа пользователя; сбой запасного пути упомянут в сообщении.
    assert outcome.reason == "auth"
    assert "Запасной провайдер" in (outcome.message or "")
    assert (outcome.done, outcome.remaining) == ("00:00–00:10", "00:10–01:00")
    assert outcome.attempts >= 2
    payload = outcome.to_json()
    assert payload["capability"] == "speech_to_text"
    assert payload["alternatives"] == []


async def test_no_user_and_no_fallback_is_capability_missing() -> None:
    harness = _Harness()

    outcome = await harness.failure(
        harness.router.run(
            user_id=None,
            capability=Capability.SPEECH_TO_TEXT,
            invoke=lambda adapter: adapter.transcribe(b"audio", mime=None),
        )
    )

    assert outcome.reason == "capability_missing"
    assert outcome.status == "unavailable"


async def test_checkable_adapter_is_created_with_user_base_url() -> None:
    """Маршрутизатор передаёт адаптеру адрес и модель ключа (для совместимых провайдеров)."""

    class _ContextAdapter(_FakeAdapter):
        async def check(self) -> str:
            return f"{self.context.base_url}:{self.context.model}"

    registry = AdapterRegistry()
    registry.register(
        AdapterSpec(
            Capability.SPEECH_TO_TEXT,
            "compatible",
            "Compatible",
            lambda context: _ContextAdapter(context, {}),
        )
    )
    store = InMemoryStore()
    repos = store.repositories()
    cipher = CredentialCipher(SecretStr(Fernet.generate_key().decode()), allow_ephemeral=False)
    user_id = uuid4()
    credential = Credential(
        id=uuid4(),
        user_id=user_id,
        provider="compatible",
        label="Compatible",
        encrypted_key=cipher.encrypt(user_id, PLAIN_KEY),
        key_hint="6789",
        kinds=(CredentialKind.SPEECH_TO_TEXT,),
        base_url="https://stt.example.com/v1",
        default_model="whisper-1",
        created_at=NOW,
    )
    await repos.credentials.save(credential)  # type: ignore[union-attr]
    router = CapabilityRouter(
        repos,
        cipher=cipher,
        registry=registry,
        runtime=Runtime(clock=lambda: NOW),
        policy=RoutingPolicy(retry_base_sec=0),
        monotonic=lambda: 0.0,
        sleep=_no_sleep,
    )
    adapter: _ContextAdapter | None = None

    async def invoke(item: object) -> str:
        nonlocal adapter
        assert isinstance(item, _ContextAdapter)
        adapter = item
        return await item.check()

    result = await router.run(user_id=user_id, capability=Capability.SPEECH_TO_TEXT, invoke=invoke)
    assert result == "https://stt.example.com/v1:whisper-1"
    assert adapter is not None
    assert adapter.context.api_key == PLAIN_KEY


async def test_slow_adapter_call_times_out_as_transient_and_next_key_is_used() -> None:
    """Таймаут одного вызова: маршрутизатор помечает ключ и идёт дальше, а не висит."""
    harness = _Harness(attempts=1, request_timeout_sec=0.02)
    user_id = uuid4()
    slow = await harness.add(user_id=user_id, priority=10)
    harness.plan[slow.id] = [0.3]
    await harness.add(user_id=user_id, priority=20)

    transcript = await harness.run(user_id=user_id)

    assert transcript.text == "расшифровано"
    stored = await harness.repos.credentials.get(slow.id)  # type: ignore[union-attr]
    assert stored is not None
    assert stored.last_error_code == "transient"
    assert stored.enabled is True


async def test_unexpected_adapter_creation_error_is_fatal_and_recorded() -> None:
    """Непредвиденная ошибка адаптера — FATAL: отказ записывается, 500 наружу не уходит."""
    store = InMemoryStore()
    repos = store.repositories()
    cipher = CredentialCipher(SecretStr(Fernet.generate_key().decode()), allow_ephemeral=False)
    registry = AdapterRegistry()

    def broken(context: AdapterContext) -> object:
        del context
        raise RuntimeError("boom")

    registry.register(
        AdapterSpec(Capability.SPEECH_TO_TEXT, "broken", "Broken", broken)  # type: ignore[arg-type]
    )
    user_id = uuid4()
    credential = Credential(
        id=uuid4(),
        user_id=user_id,
        provider="broken",
        label="Сломанный",
        encrypted_key=cipher.encrypt(user_id, PLAIN_KEY),
        key_hint="6789",
        kinds=(CredentialKind.SPEECH_TO_TEXT,),
        created_at=NOW,
    )
    await repos.credentials.save(credential)  # type: ignore[union-attr]
    router = CapabilityRouter(
        repos,
        cipher=cipher,
        registry=registry,
        runtime=Runtime(clock=lambda: NOW),
        policy=RoutingPolicy(max_attempts=1, request_timeout_sec=1),
        monotonic=lambda: 0.0,
        sleep=_no_sleep,
    )

    with pytest.raises(CapabilityUnavailableError) as info:
        await router.run(
            user_id=user_id,
            capability=Capability.SPEECH_TO_TEXT,
            invoke=lambda adapter: adapter.transcribe(b"audio", mime=None),
        )

    assert info.value.outcome.status == "failed"
    assert info.value.outcome.reason == "fatal"
    stored = await repos.credentials.get(credential.id)  # type: ignore[union-attr]
    assert stored is not None
    assert stored.last_error_code == "fatal"
    assert stored.enabled is True
