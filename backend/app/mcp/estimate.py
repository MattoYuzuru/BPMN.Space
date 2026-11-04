"""Оценка стоимости прогона для MCP и подписанный допуск на запуск (RFC-0005, RFC-0007).

Сервис оценки делает волна 2A: `services/estimate.py` и `POST /projects/{id}/runs/estimate`.
В этой ветке его ещё нет, поэтому MCP честно отказывает: `estimate_run` не выдумывает числа, а
`start_run` без свежей оценки отклоняется. Точка подключения — функция `build_estimator` внизу
файла: интегратор возвращает адаптер над сервисом оценки, не меняя инструменты MCP.

Допуск на запуск — подписанный HMAC-тикет без таблицы в БД: он привязан к пользователю, проекту,
режиму и профилю, живёт `MCP_ESTIMATE_TTL_SEC` и проверяется в `start_run`. Протухший или
чужой тикет отклоняется: «запустить без свежей оценки» нельзя.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID, uuid4

from app.domain.models import RunMode
from app.services.errors import InvalidInputError, UnavailableError

if TYPE_CHECKING:
    from app.container import Container

__all__ = [
    "ESTIMATE_UNAVAILABLE_MESSAGE",
    "EstimateTicket",
    "RunEstimate",
    "RunEstimator",
    "TicketSigner",
    "UnavailableEstimator",
    "build_estimator",
]

ESTIMATE_UNAVAILABLE_MESSAGE = (
    "Оценка стоимости прогона пока недоступна: сервер ещё не подключил модель с ценами. "
    "Запуск без оценки не выполняется — запросите оценку позже"
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
    """Оценка прогона для внешнего агента. `complete=false` — часть цен неизвестна."""

    tokens: Range
    cost: Range
    duration_sec: Range
    complete: bool = False
    currency: str = "USD"
    breakdown: tuple[dict[str, Any], ...] = field(default_factory=tuple[dict[str, Any], ...])

    def to_json(self) -> dict[str, Any]:
        return {
            "tokens": self.tokens.to_json(),
            "cost": {**self.cost.to_json(), "currency": self.currency},
            "duration_sec": self.duration_sec.to_json(),
            "complete": self.complete,
            "breakdown": list(self.breakdown),
        }


class RunEstimator(Protocol):
    """Порт оценки стоимости прогона (реализует волна 2A поверх `services/estimate.py`)."""

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


class UnavailableEstimator:
    """До интеграции 2A: честный отказ вместо выдуманных чисел."""

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
    """Разобранный допуск на запуск: что именно и кем было оценено."""

    estimate_id: UUID
    project_id: UUID
    user_id: UUID
    mode: RunMode
    profile: dict[str, Any] | None
    expires_at: datetime


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
    ) -> tuple[str, EstimateTicket]:
        now = datetime.now(UTC)
        claims = {
            "v": _TICKET_VERSION,
            "eid": str(uuid4()),
            "pid": str(project_id),
            "uid": str(user_id),
            "mode": mode.value,
            "profile": json.loads(_canonical_profile(profile)) if profile is not None else None,
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
        )
        return ticket, parsed

    def decode(self, ticket: str) -> EstimateTicket:
        """Проверить подпись и срок тикета. Содержимое читается из подписанных claims."""
        try:
            payload, signature = ticket.split(_TICKET_SEPARATOR, 1)
            expected = self._sign(payload)
            if not hmac.compare_digest(signature, expected):
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


def build_estimator(container: Container) -> RunEstimator:  # noqa: ARG001
    """Подключение настоящей оценки (волна 2A) — единственная правка интегратора.

    Когда в контейнере появится сервис оценки, верните адаптер над ним, например::

        return ServiceEstimator(container.estimate)

    Адаптер должен реализовать `RunEstimator.estimate`: получить оценку сервиса (RFC-0005:
    `tokens{min,max}`, `cost{min,max,currency}`, `duration`, `breakdown[]`, `complete`) и
    перевести её в `RunEstimate`. Пока сервиса нет — `UnavailableEstimator`:
    `estimate_run` отвечает понятным отказом, `start_run` без оценки невозможен.
    """
    return UnavailableEstimator()


def make_ticket_signer(secret: str | None, *, ttl_sec: int) -> TicketSigner:
    """Подписыватель допусков: явный секрет из настроек или эфемерный на процесс."""
    raw = secret.encode("utf-8") if secret else secrets.token_bytes(32)
    return TicketSigner(raw, ttl_sec=ttl_sec)


def ticket_ttl_seconds(seconds: float) -> int:
    return max(int(seconds), 1)
