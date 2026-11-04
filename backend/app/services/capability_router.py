"""Маршрутизация возможностей по ключам пользователя (RFC-0006, шаг 1).

Для каждой возможности сервер перебирает включённые ключи по приоритету. Ошибки делятся на
классы — повторяются только временные, исчерпанная квота и отклонённый ключ помечаются и
пропускаются без повторов, несовместимый материал пробует следующий ключ, фатальная ошибка
останавливает инструмент. Для каждого ключа есть предохранитель: после нескольких подряд
отказов ключ не тратит повторы на заведомо мёртвый адрес.

Наружу уходит структурный результат (`CapabilityOutcome`): статус, причина-класс, что сделано,
что осталось и альтернативы. Текст провайдера и открытый ключ в результат не попадают.
"""

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, TypeVar, cast
from uuid import UUID

from app.domain.capabilities import (
    CAPABILITY_LABELS,
    ERROR_CLASS_MESSAGES,
    REASON_CAPABILITY_MISSING,
    Capability,
    CapabilityError,
    CapabilityOutcome,
    CapabilityUnavailableError,
    ErrorClass,
)
from app.domain.credentials import Credential
from app.infra.crypto import CredentialCipher, CredentialCipherError
from app.infra.repositories.base import Repositories
from app.ingest.adapters import AdapterContext, AdapterRegistry
from app.ingest.stt import NoSpeechError, SpeechToText, Transcript
from app.services.common import Runtime

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RoutingPolicy:
    """Повторы, паузы и предохранитель маршрутизатора; значения — из `config.py`."""

    max_attempts: int = 2
    retry_base_sec: float = 1.0
    retry_max_sec: float = 30.0
    max_retry_after_sec: float = 30.0
    breaker_threshold: int = 3
    breaker_cooldown_sec: float = 60.0
    quota_cooldown_sec: float = 3600.0
    # Один вызов адаптера (запрос к провайдеру) не дольше этого: иначе внешний дедлайн
    # обработки записи оборвёт маршрутизатор до перехода к следующему ключу/серверу.
    request_timeout_sec: float = 120.0
    # Бюджет на весь перебор ключей и запасной путь; больше — отказ `transient`.
    run_deadline_sec: float = 600.0


@dataclass(slots=True)
class _BreakerState:
    """Счётчик подряд идущих отказов ключа и время размыкания предохранителя."""

    failures: int = 0
    open_until: float = 0.0


# Что предложить вместо недоступной возможности, если у пользователя есть ключ под неё.
_ALTERNATIVES: dict[Capability, tuple[tuple[Capability, str], ...]] = {
    Capability.SPEECH_TO_TEXT: (
        (Capability.VISION, "vision:frames"),
        (Capability.VIDEO_UNDERSTANDING, "video_understanding"),
    ),
    Capability.VIDEO_UNDERSTANDING: ((Capability.VISION, "vision:frames"),),
    Capability.OCR: ((Capability.VISION, "vision:pages"),),
    Capability.VISION: ((Capability.OCR, "ocr:pages"),),
}

# Понятные пользователю сообщения по классу ошибки; подпись ключа подставляется.
_CLASS_MESSAGES: dict[ErrorClass, str] = {
    ErrorClass.AUTH: "«{label}» отклонён провайдером. Проверьте ключ в настройках",
    ErrorClass.QUOTA_EXHAUSTED: "«{label}»: закончилась квота",
    ErrorClass.TRANSIENT: "«{label}»: провайдер временно недоступен",
    ErrorClass.UNSUPPORTED: "«{label}»: провайдер не принял материал",
    ErrorClass.FATAL: "«{label}»: ошибка провайдера",
}

_MAX_MESSAGE_CHARS = 500


@dataclass(slots=True)
class _CredentialAttempt:
    """Итог попытки одного ключа: значение при успехе либо ошибка и признак фатальности."""

    value: object | None = None
    found: bool = False
    attempts: int = 0
    fatal: bool = False
    error: CapabilityError | None = None


class CapabilityRouter:
    """Перебор ключей пользователя по приоритету с классами ошибок и предохранителем."""

    def __init__(
        self,
        repos: Repositories,
        *,
        cipher: CredentialCipher,
        registry: AdapterRegistry,
        runtime: Runtime,
        policy: RoutingPolicy | None = None,
        allowed_private_hosts: tuple[str, ...] = (),
        transport=None,
        adapter_client_factory=None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_value: Callable[[], float] = random.random,
    ) -> None:
        self._repos = repos
        self._cipher = cipher
        self._registry = registry
        self._rt = runtime
        self._policy = policy or RoutingPolicy()
        self._allowed_private = allowed_private_hosts
        self._transport = transport
        self._adapter_client_factory = adapter_client_factory
        self._monotonic = monotonic
        self._sleep = sleep
        self._random = random_value
        # Состояние предохранителей живёт в процессе: один API-воркер (RFC §9).
        self._breakers: dict[UUID, _BreakerState] = {}

    async def run(
        self,
        *,
        user_id: UUID | None,
        capability: Capability,
        invoke: Callable[[Any], Awaitable[T]],
        fallback: Callable[[], Awaitable[T]] | None = None,
        progress: Callable[[], tuple[str | None, str | None]] | None = None,
    ) -> T:
        """Выполняет возможность на первом рабочем ключе.

        `invoke` вызывает метод адаптера; `fallback` — запасной путь оператора (серверный
        провайдер), `progress` — что уже покрыто и что осталось (для отказа маршрутизации).
        При исчерпании всех путей бросает `CapabilityUnavailableError` со структурным итогом.
        """
        attempts = 0
        fatal = False
        started = self._monotonic()
        last_error: CapabilityError | None = None
        last_credential: Credential | None = None
        fallback_error: CapabilityError | None = None
        for credential in await self._candidates(user_id, capability, self._rt.clock()):
            remaining = self._remaining(started)
            if remaining is not None and remaining <= 0:
                last_error = CapabilityError(
                    ErrorClass.TRANSIENT, "Перебор ключей занял слишком много времени"
                )
                last_credential = credential
                break
            if self._breaker_open(credential.id):
                # Предохранитель разомкнут: ключ временно не трогаем, но причину показываем.
                last_error = CapabilityError(
                    ErrorClass.TRANSIENT,
                    "Ключ временно отключён после нескольких отказов подряд",
                )
                last_credential = credential
                continue
            tried = await self._attempt(
                credential,
                capability,
                invoke,
                timeout_sec=self._call_timeout(remaining),
            )
            attempts += tried.attempts
            if tried.found:
                return cast(T, tried.value)
            last_error, last_credential = tried.error, credential
            if tried.fatal:
                fatal = True
                break
        if fallback is not None and not fatal:
            remaining = self._remaining(started)
            if remaining is not None and remaining <= 0:
                fallback_error = CapabilityError(
                    ErrorClass.TRANSIENT, "Обработка заняла слишком много времени"
                )
            else:
                try:
                    value, used = await self._with_retries(
                        fallback, timeout_sec=self._call_timeout(remaining)
                    )
                except CapabilityError as error:
                    attempts += error.attempts
                    fallback_error = error
                else:
                    attempts += used
                    return value
        done, remaining = progress() if progress is not None else (None, None)
        outcome = CapabilityOutcome(
            capability=capability,
            status="failed" if fatal else "unavailable",
            reason=self._failure_reason(last_error, fallback_error),
            done=done,
            remaining=remaining,
            alternatives=self._alternatives(capability, await self._all_credentials(user_id)),
            attempts=attempts,
            message=self._failure_message(capability, last_error, last_credential, fallback_error),
            credential_id=last_credential.id if last_credential is not None else None,
        )
        raise CapabilityUnavailableError(outcome)

    async def _attempt(
        self,
        credential: Credential,
        capability: Capability,
        invoke: Callable[[Any], Awaitable[T]],
        *,
        timeout_sec: float | None,
    ) -> "_CredentialAttempt":
        """Один ключ: расшифровка, адаптер, повторы и пометка отказа по классу."""
        try:
            api_key = self._cipher.decrypt(
                credential.user_id, credential.encrypted_key
            ).get_secret_value()
        except CredentialCipherError as error:
            failure = CapabilityError(ErrorClass.FATAL, str(error))
            await self._record_failure(credential, failure)
            return _CredentialAttempt(error=failure)
        try:
            adapter = self._registry.create(
                capability,
                credential.provider,
                AdapterContext(
                    api_key=api_key,
                    base_url=credential.base_url,
                    model=credential.default_model,
                    credential_id=credential.id,
                    transport=self._transport,
                    client_factory=self._adapter_client_factory,
                    allowed_private_hosts=self._allowed_private,
                ),
            )
        except CapabilityError as error:
            await self._record_failure(credential, error)
            return _CredentialAttempt(error=error, fatal=error.error_class is ErrorClass.FATAL)
        except Exception:
            # Непредвиденная ошибка подготовки адаптера: причина одна, повтор бесполезен.
            logger.exception("Не удалось подготовить адаптер возможности %s", capability.value)
            failure = CapabilityError(ErrorClass.FATAL, "Не удалось подготовить адаптер провайдера")
            await self._record_failure(credential, failure)
            return _CredentialAttempt(error=failure, fatal=True)
        try:
            value, used = await self._with_retries(lambda: invoke(adapter), timeout_sec=timeout_sec)
        except CapabilityError as error:
            await self._record_failure(credential, error)
            return _CredentialAttempt(
                attempts=error.attempts,
                error=error,
                fatal=error.error_class is ErrorClass.FATAL,
            )
        finally:
            await adapter.aclose()
        self._breakers.pop(credential.id, None)
        await self._mark_success(credential)
        return _CredentialAttempt(value=value, found=True, attempts=used)

    async def _candidates(
        self, user_id: UUID | None, capability: Capability, now: datetime
    ) -> list[Credential]:
        """Включённые, не исчерпанные и не разомкнутые предохранителем ключи по приоритету."""
        if user_id is None:
            return []
        repo = self._repos.credentials
        if repo is None:
            return []
        own = [
            item
            for item in await repo.list_by_user(user_id)
            if item.enabled and item.covers(capability) and not item.is_exhausted(now)
        ]
        own.sort(key=lambda item: (item.priority, item.created_at, str(item.id)))
        return own

    async def _all_credentials(self, user_id: UUID | None) -> list[Credential]:
        repo = self._repos.credentials
        if user_id is None or repo is None:
            return []
        return await repo.list_by_user(user_id)

    def _alternatives(
        self, capability: Capability, credentials: list[Credential]
    ) -> tuple[str, ...]:
        """Что можно предложить вместо отказавшей возможности, если ключ под неё есть."""
        available = {
            item_capability
            for item in credentials
            if item.enabled
            for item_capability in item.capabilities
        }
        return tuple(
            label
            for alternative, label in _ALTERNATIVES.get(capability, ())
            if alternative in available
        )

    async def _with_retries(
        self, call: Callable[[], Awaitable[T]], *, timeout_sec: float | None = None
    ) -> tuple[T, int]:
        """Вызов с повторами временных сбоев; возвращает результат и число попыток.

        `timeout_sec` ограничивает **один** вызов адаптера, а не весь перебор ключей: так
        медленный ключ не обрывает маршрутизацию до перехода к следующему ключу или серверу.
        """
        attempts = 0
        while True:
            attempts += 1
            try:
                if timeout_sec is None:
                    return await call(), attempts
                return await asyncio.wait_for(call(), timeout=timeout_sec), attempts
            except CapabilityError as error:
                error.attempts = attempts
                if error.error_class is not ErrorClass.TRANSIENT or attempts >= max(
                    self._policy.max_attempts, 1
                ):
                    raise
                await self._pause(attempts, error.retry_after_sec)
            except TimeoutError:
                error = CapabilityError(
                    ErrorClass.TRANSIENT, "Провайдер не ответил вовремя: повторите позже"
                )
                error.attempts = attempts
                if attempts >= max(self._policy.max_attempts, 1):
                    raise error from None
                await self._pause(attempts, None)
            except NoSpeechError:
                raise
            except Exception:
                # Непредвиденная ошибка адаптера не должна уходить как 500 и терять отказ:
                # помечаем её фатальной, чтобы ключ получил `last_error_code`.
                logger.exception("Адаптер возможности вернул непредвиденную ошибку")
                raise CapabilityError(
                    ErrorClass.FATAL, "Провайдер вернул непредвиденную ошибку"
                ) from None

    async def _pause(self, attempt: int, retry_after_sec: float | None) -> None:
        """Экспоненциальная пауза с джиттером; `Retry-After` провайдера учитывается."""
        if retry_after_sec is not None:
            delay = min(retry_after_sec, self._policy.max_retry_after_sec)
        else:
            delay = min(
                self._policy.retry_base_sec * (2 ** (attempt - 1)),
                self._policy.retry_max_sec,
            )
            delay += self._random() * delay * 0.25
        if delay > 0:
            await self._sleep(delay)

    def _remaining(self, started: float) -> float | None:
        """Сколько секунд осталось на перебор ключей; `None` — бюджет не задан."""
        if self._policy.run_deadline_sec <= 0:
            return None
        return max(self._policy.run_deadline_sec - (self._monotonic() - started), 0.0)

    def _call_timeout(self, remaining: float | None) -> float:
        """Таймаут одного вызова адаптера: запрос провайдера и не больше остатка бюджета."""
        if remaining is None:
            return self._policy.request_timeout_sec
        return max(min(self._policy.request_timeout_sec, remaining), 0.1)

    def _breaker_open(self, credential_id: UUID) -> bool:
        state = self._breakers.get(credential_id)
        return state is not None and state.open_until > self._monotonic()

    def _count_breaker_failure(self, credential_id: UUID) -> None:
        state = self._breakers.setdefault(credential_id, _BreakerState())
        state.failures += 1
        if state.failures >= max(self._policy.breaker_threshold, 1):
            state.open_until = self._monotonic() + self._policy.breaker_cooldown_sec

    async def _record_failure(self, credential: Credential, error: CapabilityError) -> None:
        """Помечает ключ по классу ошибки: пауза при квоте, отключение при отказе ключа."""
        repo = self._repos.credentials
        if repo is None:
            return
        now = self._rt.clock()
        exhausted_until: datetime | None = None
        disable = False
        if error.error_class is ErrorClass.QUOTA_EXHAUSTED:
            cooldown = error.retry_after_sec or self._policy.quota_cooldown_sec
            exhausted_until = now + timedelta(seconds=cooldown)
        elif error.error_class is ErrorClass.AUTH:
            disable = True
        elif error.error_class in {ErrorClass.TRANSIENT, ErrorClass.FATAL}:
            self._count_breaker_failure(credential.id)
        message = _CLASS_MESSAGES.get(error.error_class, ERROR_CLASS_MESSAGES[error.error_class])
        try:
            await repo.mark_failure(
                credential.id,
                now,
                error=message.format(label=credential.label)[:_MAX_MESSAGE_CHARS],
                error_code=error.error_class.value,
                exhausted_until=exhausted_until,
                disable=disable,
            )
        except Exception:
            logger.exception("Не удалось записать отказ ключа %s", credential.id)

    async def _mark_success(self, credential: Credential) -> None:
        repo = self._repos.credentials
        if repo is None:
            return
        try:
            await repo.mark_used(credential.id, self._rt.clock(), None)
        except Exception:
            logger.exception("Не удалось записать использование ключа %s", credential.id)

    @staticmethod
    def _failure_reason(
        last_error: CapabilityError | None, fallback_error: CapabilityError | None
    ) -> str:
        """Класс причины отказа: сначала рабочего ключа пользователя, потом запасного пути."""
        error = last_error or fallback_error
        return error.error_class.value if error is not None else REASON_CAPABILITY_MISSING

    @staticmethod
    def _failure_message(
        capability: Capability,
        last_error: CapabilityError | None,
        credential: Credential | None,
        fallback_error: CapabilityError | None,
    ) -> str:
        """Понятный итог для источника и технического вопроса: без текста провайдера."""
        title = CAPABILITY_LABELS[capability]
        if last_error is None and fallback_error is None:
            return f"Нет ключа для возможности «{title}». Добавьте ключ в настройках"
        if last_error is None or credential is None:
            error = last_error or fallback_error
            assert error is not None  # noqa: S101 — проверено выше
            reason = ERROR_CLASS_MESSAGES[error.error_class].lower()
            return f"Возможность «{title}» недоступна: {reason}"
        message = _CLASS_MESSAGES.get(
            last_error.error_class, ERROR_CLASS_MESSAGES[last_error.error_class]
        ).format(label=credential.label)
        if fallback_error is not None:
            message += (
                ". Запасной провайдер сервера: "
                f"{ERROR_CLASS_MESSAGES[fallback_error.error_class].lower()}"
            )
        return message


class RoutedSpeechToText:
    """Распознавание речи на ключах пользователя; запасной путь — серверный провайдер.

    `server=None` (`STT_PROVIDER=none`): запасного пути нет — без ключа пользователя запись
    не распознаётся, а источник объясняет, что нужно добавить ключ.
    """

    def __init__(self, router: CapabilityRouter, *, server: SpeechToText | None) -> None:
        self._router = router
        self._server = server

    def for_user(self, user_id: UUID | None) -> SpeechToText:
        """Адаптер для одной записи или голосовой заметки вызывающего пользователя."""
        return _BoundSpeechToText(self._router, self._server, user_id)

    def provider_for(self, user_id: UUID | None) -> str:  # noqa: ARG002 — подпись для слоя выше
        """Провайдер, которым будет обработана запись: подпись для `derivation` до запуска."""
        return "user"


class _BoundSpeechToText:
    """`SpeechToText` одного пользователя: каждый сегмент идёт через маршрутизатор."""

    def __init__(
        self,
        router: CapabilityRouter,
        server: SpeechToText | None,
        user_id: UUID | None,
    ) -> None:
        self._router = router
        self._server = server
        self._user_id = user_id

    async def transcribe(self, data: bytes, *, mime: str | None) -> Transcript:
        server = self._server

        async def server_fallback() -> Transcript:
            assert server is not None  # noqa: S101 — запасной путь передаётся только с сервером
            return await server.transcribe(data, mime=mime)

        return await self._router.run(
            user_id=self._user_id,
            capability=Capability.SPEECH_TO_TEXT,
            invoke=lambda adapter: _transcribe_with(adapter, data, mime),
            fallback=server_fallback if server is not None else None,
        )


async def _transcribe_with(adapter: object, data: bytes, mime: str | None) -> Transcript:
    """Вызов `transcribe` у адаптера возможности; протокол сужен, чтобы не тянуть типы."""
    transcribe = getattr(adapter, "transcribe", None)
    if transcribe is None:
        raise CapabilityError(ErrorClass.UNSUPPORTED, "Этот провайдер не умеет распознавание речи")
    return await transcribe(data, mime=mime)
