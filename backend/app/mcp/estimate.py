"""Оценка прогона для MCP и подписанный допуск на запуск (RFC-0005, RFC-0007).

Оценку считает сервис волны 2A (`services/estimate.py`: план вызовов, токены, цены модели и
время). MCP не дублирует расчёт: `ServiceEstimator` переводит ответ сервиса в компактную модель
для агента, сохраняя честность диапазона — `complete=false` и `cost=null`, если цены модели
неизвестны (mock, совместимый провайдер без прайса). Ошибки профиля (неизвестный `effort`,
несовместимая модель, нет ключа) приходят из сервиса русскими `ServiceError` и превращаются в
ошибку инструмента с понятным текстом.

Допуск на запуск — подписанный HMAC-тикет без таблицы в БД: он привязан к пользователю, проекту,
режиму и профилю, живёт `MCP_ESTIMATE_TTL_SEC` и проверяется в `start_run`. Протухший или
чужой тикет отклоняется: «запустить без свежей оценки» нельзя. Оценка, полученная до появления
сервиса (или на стенде без него), честно недоступна: `UnavailableEstimator`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID, uuid4

from pydantic import SecretStr

from app.domain.models import RunMode
from app.services.errors import InvalidInputError, UnavailableError
from app.services.runs import RunProfile

if TYPE_CHECKING:
    from app.container import Container

__all__ = [
    "ESTIMATE_REUSED_MESSAGE",
    "ESTIMATE_UNAVAILABLE_MESSAGE",
    "EstimateTicket",
    "Range",
    "RedeemedEstimates",
    "RunEstimate",
    "RunEstimator",
    "ServiceEstimator",
    "TicketSigner",
    "UnavailableEstimator",
    "build_estimator",
]

ESTIMATE_UNAVAILABLE_MESSAGE = (
    "Оценка стоимости прогона пока недоступна: сервер не подключил сервис оценки. "
    "Запуск без оценки не выполняется — запросите оценку позже"
)
ESTIMATE_REUSED_MESSAGE = (
    "Эта оценка уже использована для запуска. Вызовите estimate_run снова: допуск на запуск "
    "одноразовый"
)
ESTIMATE_EXPIRED_MESSAGE = (
    "Оценка устарела или не совпадает с запросом. Вызовите estimate_run снова и передайте "
    "новый estimate_token"
)
_TICKET_VERSION = 1
_TICKET_SEPARATOR = "."
_HMAC_CHARS = 32


@dataclass(frozen=True, slots=True)
class Range:
    """Диапазон оценки: число от min до max (RFC-0005: ответ — диапазон, а не одно число)."""

    min: float
    max: float

    def to_json(self) -> dict[str, float]:
        return {"min": self.min, "max": self.max}


@dataclass(frozen=True, slots=True)
class RunEstimate:
    """Оценка прогона для внешнего агента.

    `tokens`/`calls`/`duration_sec` — всегда диапазон; `cost` — только если цены модели известны.
    `complete=false` — часть цен неизвестна: агент обязан сказать человеку, что оценка неполная.
    """

    tokens: Range
    calls: Range
    duration_sec: Range
    cost: Range | None = None
    complete: bool = False
    currency: str = "USD"
    breakdown: tuple[dict[str, Any], ...] = field(default_factory=tuple[dict[str, Any], ...])
    model: str | None = None
    provider: str | None = None
    priced_on: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple[str, ...])

    def to_json(self) -> dict[str, Any]:
        return {
            "tokens": self.tokens.to_json(),
            "calls": self.calls.to_json(),
            "cost": (
                {**self.cost.to_json(), "currency": self.currency}
                if self.cost is not None
                else None
            ),
            "duration_sec": self.duration_sec.to_json(),
            "complete": self.complete,
            "breakdown": list(self.breakdown),
            "model": self.model,
            "provider": self.provider,
            "priced_on": self.priced_on,
            "notes": list(self.notes),
        }


class RunEstimator(Protocol):
    """Порт оценки стоимости прогона (реализует `ServiceEstimator` над `services/estimate.py`)."""

    async def estimate(
        self,
        *,
        project_id: UUID,
        mode: RunMode,
        profile: dict[str, Any] | None,
        user_id: UUID,
    ) -> RunEstimate:
        """Оценка для владельца токена; профиль — как его пришлёт клиент MCP."""
        ...


def _domain_profile(profile: dict[str, Any] | None) -> RunProfile | None:
    """JSON-профиль MCP → профиль прогона сервисного слоя (только разрешённые поля)."""
    if profile is None:
        return None
    return RunProfile(effort=profile.get("effort"), semantic_review=profile.get("semantic_review"))


def _from_domain(estimate: Any) -> RunEstimate:
    """Ответ `services/estimate.py` (RFC-0005) → компактная оценка MCP.

    Цену отдаём, только если известны обе границы: иначе `cost=null` и `complete=false`, чтобы
    агент не показывал «ноль» вместо неизвестной стоимости.
    """
    domain_cost = estimate.cost
    cost: Range | None = None
    if (
        domain_cost is not None
        and domain_cost.min_usd is not None
        and domain_cost.max_usd is not None
    ):
        cost = Range(min=domain_cost.min_usd, max=domain_cost.max_usd)
    complete = bool(estimate.complete) and cost is not None
    breakdown: list[dict[str, Any]] = []
    for stage in estimate.breakdown:
        stage_cost = None
        if (
            stage.cost is not None
            and stage.cost.min_usd is not None
            and stage.cost.max_usd is not None
        ):
            stage_cost = {
                "min": stage.cost.min_usd,
                "max": stage.cost.max_usd,
                "currency": stage.cost.currency,
            }
        breakdown.append(
            {
                "stage": stage.stage,
                "label": stage.label,
                "calls": {"min": stage.calls.min, "max": stage.calls.max},
                "tokens_in": {"min": stage.tokens_in.min, "max": stage.tokens_in.max},
                "tokens_out": {"min": stage.tokens_out.min, "max": stage.tokens_out.max},
                "cost": stage_cost,
            }
        )
    return RunEstimate(
        tokens=Range(min=estimate.tokens.min, max=estimate.tokens.max),
        calls=Range(min=estimate.calls.min, max=estimate.calls.max),
        duration_sec=Range(min=estimate.duration_sec.min, max=estimate.duration_sec.max),
        cost=cost,
        complete=complete,
        currency=domain_cost.currency if domain_cost is not None else "USD",
        breakdown=tuple(breakdown),
        model=estimate.model,
        provider=estimate.provider,
        priced_on=estimate.priced_on.isoformat() if estimate.priced_on is not None else None,
        notes=tuple(estimate.notes),
    )


class ServiceEstimator:
    """Адаптер над `container.estimate` (сервис оценки волны 2A, RFC-0005 шаг 4).

    Ошибки сервиса (`InvalidInputError`: неизвестный `effort`, нет ключа модели, пустой проект)
    не переупаковываются: инструмент покажет агенту русский текст причины.
    """

    def __init__(self, service: Any) -> None:
        self._service = service

    async def estimate(
        self,
        *,
        project_id: UUID,
        mode: RunMode,
        profile: dict[str, Any] | None,
        user_id: UUID,
    ) -> RunEstimate:
        estimate = await self._service.estimate(
            project_id,
            mode=mode,
            created_by=user_id,
            profile=_domain_profile(profile),
        )
        return _from_domain(estimate)


class UnavailableEstimator:
    """Запасной путь, если сервис оценки не подключён (не притворяется, что умеет считать)."""

    async def estimate(
        self,
        *,
        project_id: UUID,
        mode: RunMode,
        profile: dict[str, Any] | None,
        user_id: UUID,
    ) -> RunEstimate:
        _ = (project_id, mode, profile, user_id)  # порт без реализации: поля не читаются
        raise UnavailableError(ESTIMATE_UNAVAILABLE_MESSAGE)


@dataclass(frozen=True, slots=True)
class EstimateTicket:
    """Разобранный допуск на запуск: что именно, кем и на какой модели оценено."""

    estimate_id: UUID
    project_id: UUID
    user_id: UUID
    mode: RunMode
    profile: dict[str, Any] | None
    expires_at: datetime
    # Модель и провайдер из оценки: start_run сверяет их с фактическим выбором, чтобы
    # оценка не разошлась с прогоном при смене ключа/модели по умолчанию.
    model: str | None = None
    provider: str | None = None


def _canonical_profile(profile: dict[str, Any] | None) -> str:
    return json.dumps(profile or None, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


class TicketSigner:
    """HMAC-подпись оценки: без таблицы в БД и без состояния между рестартами.

    Секрет задаётся `MCP_ESTIMATE_SECRET`; без него берётся случайный на процесс — после
    перезапуска старые оценки потребуют повторного `estimate_run`, что безопасно.
    """

    def __init__(self, secret: bytes, *, ttl_sec: int) -> None:
        self._secret = secret
        self._ttl = ttl_sec

    def issue(
        self,
        *,
        project_id: UUID,
        user_id: UUID,
        mode: RunMode,
        profile: dict[str, Any] | None,
        model: str | None = None,
        provider: str | None = None,
    ) -> tuple[str, EstimateTicket]:
        now = datetime.now(UTC)
        claims = {
            "v": _TICKET_VERSION,
            "eid": str(uuid4()),
            "pid": str(project_id),
            "uid": str(user_id),
            "mode": mode.value,
            "profile": json.loads(_canonical_profile(profile)) if profile is not None else None,
            "model": model,
            "provider": provider,
            "exp": int((now + timedelta(seconds=self._ttl)).timestamp()),
        }
        payload = _b64encode(json.dumps(claims, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        ticket = f"{payload}{_TICKET_SEPARATOR}{self._sign(payload)}"
        parsed = EstimateTicket(
            estimate_id=UUID(claims["eid"]),
            project_id=project_id,
            user_id=user_id,
            mode=mode,
            profile=claims["profile"],
            expires_at=datetime.fromtimestamp(claims["exp"], tz=UTC),
            model=model,
            provider=provider,
        )
        return ticket, parsed

    def decode(self, ticket: str) -> EstimateTicket:
        """Проверить подпись и срок тикета. Содержимое читается из подписанных claims."""
        try:
            payload, signature = ticket.split(_TICKET_SEPARATOR, 1)
            expected = self._sign(payload)
            try:
                matches = hmac.compare_digest(signature, expected)
            except TypeError as error:
                # Подпись с не-ASCII символами не сравнивается побайтово: это не наш тикет.
                raise InvalidInputError(ESTIMATE_EXPIRED_MESSAGE) from error
            if not matches:
                raise InvalidInputError(ESTIMATE_EXPIRED_MESSAGE)
            claims = json.loads(_b64decode(payload))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise InvalidInputError(ESTIMATE_EXPIRED_MESSAGE) from error
        if claims.get("v") != _TICKET_VERSION:
            raise InvalidInputError(ESTIMATE_EXPIRED_MESSAGE)
        expires_at = datetime.fromtimestamp(int(claims.get("exp", 0)), tz=UTC)
        if expires_at <= datetime.now(UTC):
            raise InvalidInputError(ESTIMATE_EXPIRED_MESSAGE)
        return EstimateTicket(
            estimate_id=UUID(str(claims["eid"])),
            project_id=UUID(str(claims["pid"])),
            user_id=UUID(str(claims["uid"])),
            mode=RunMode(str(claims["mode"])),
            profile=claims.get("profile"),
            expires_at=expires_at,
            model=str(claims["model"]) if claims.get("model") is not None else None,
            provider=str(claims["provider"]) if claims.get("provider") is not None else None,
        )

    def verify(
        self,
        ticket: str,
        *,
        project_id: UUID,
        user_id: UUID,
        mode: RunMode,
        profile: dict[str, Any] | None,
    ) -> EstimateTicket:
        """Дополнительно сверить тикет с запросом; расхождение — тот же `422`."""
        parsed = self.decode(ticket)
        if (
            parsed.project_id != project_id
            or parsed.user_id != user_id
            or parsed.mode is not mode
            or _canonical_profile(parsed.profile) != _canonical_profile(profile)
        ):
            raise InvalidInputError(ESTIMATE_EXPIRED_MESSAGE)
        return parsed

    def _sign(self, payload: str) -> str:
        digest = hmac.new(self._secret, payload.encode("ascii"), hashlib.sha256).hexdigest()
        return digest[:_HMAC_CHARS]


@dataclass(slots=True)
class RedeemedEstimates:
    """Использованные допуски: один `estimate_token` — один запуск.

    Хранится в памяти процесса (backend работает одним worker) и живёт TTL допустимого
    тикета. После перезапуска история теряется — безопасность это не снижает, потому что
    сама оценка живёт `MCP_ESTIMATE_TTL_SEC`, а секрет подписи по умолчанию эфемерный.
    """

    ttl_sec: int
    clock: Callable[[], float] = time.monotonic
    _redeemed: dict[UUID, float] = field(default_factory=dict[UUID, float])

    def redeem(self, estimate_id: UUID) -> None:
        now = self.clock()
        horizon = now - self.ttl_sec
        for key in [key for key, at in self._redeemed.items() if at <= horizon]:
            del self._redeemed[key]
        if estimate_id in self._redeemed:
            raise InvalidInputError(ESTIMATE_REUSED_MESSAGE)
        self._redeemed[estimate_id] = now

    def used(self, estimate_id: UUID) -> bool:
        return estimate_id in self._redeemed


def build_estimator(container: Container) -> RunEstimator:
    """Оценка прогона: адаптер над `container.estimate` (волна 2A), иначе честный отказ.

    `services/estimate.py` есть в контейнере вместе с оценкой стоимости RFC-0005; если сервиса
    нет (урезанный стенд), MCP не выдумывает числа и `start_run` без оценки невозможен.
    """
    service = getattr(container, "estimate", None)
    if service is None:
        return UnavailableEstimator()
    return ServiceEstimator(service)


def make_ticket_signer(secret: str | SecretStr | None, *, ttl_sec: int) -> TicketSigner:
    """Подписыватель допусков: явный секрет из настроек или эфемерный на процесс."""
    if isinstance(secret, SecretStr):
        secret = secret.get_secret_value()
    raw = secret.encode("utf-8") if secret else secrets.token_bytes(32)
    return TicketSigner(raw, ttl_sec=ttl_sec)


def ticket_ttl_seconds(seconds: float) -> int:
    return max(int(seconds), 1)
