"""Анти-спам ограничение частоты запросов.

Скользящее окно в памяти одного процесса (uvicorn запускается с одним воркером), без новой
инфраструктуры. Лимиты щедрые и задаются в `config.py`: цель — остановить скрипты и подбор
пароля, а не ограничить обычную работу. При перезапуске счётчики обнуляются.

Три корзины: весь API на IP, вход и регистрация на IP, «дорогие» вызовы на аккаунт и на IP
(прогоны, помощник, расшифровка, загрузка файла — за ними платные провайдеры).
"""

import math
import time
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from app.api.auth import OptionalUserDep
from app.config import Settings

WINDOW_SEC = 60.0
_MAX_KEYS = 50_000  # потолок числа ключей: защита памяти от перебора адресов
_AUTH_PATHS = ("/auth/session/login", "/auth/register")


@dataclass(slots=True)
class SlidingWindowLimiter:
    """Не более `limit` событий на ключ за `window` секунд."""

    limit: int
    window: float = WINDOW_SEC
    clock: Callable[[], float] = time.monotonic
    _hits: OrderedDict[str, deque[float]] = field(default_factory=OrderedDict[str, deque[float]])

    def check(self, key: str) -> float | None:
        """Записать событие. None — можно; иначе секунды до освобождения слота."""
        now = self.clock()
        horizon = now - self.window
        hits = self._hits.get(key)
        if hits is None:
            if len(self._hits) >= _MAX_KEYS:
                self._evict(horizon)
            hits = self._hits[key] = deque()
        else:
            self._hits.move_to_end(key)  # порядок словаря = давность последнего обращения
        while hits and hits[0] <= horizon:
            hits.popleft()
        if len(hits) >= self.limit:
            return max(hits[0] + self.window - now, 0.0)
        hits.append(now)
        return None

    def _evict(self, horizon: float) -> None:
        """Освободить место для нового ключа за O(1) в среднем: ключи упорядочены по давности,
        поэтому устаревшие лежат в начале. Если все активны, вытесняется самый давний."""
        self._hits.popitem(last=False)  # минимум один слот освобождаем всегда
        while self._hits:
            hits = next(iter(self._hits.values()))
            if hits and hits[-1] > horizon:
                return
            self._hits.popitem(last=False)


@dataclass(frozen=True, slots=True)
class RateLimits:
    enabled: bool
    api: SlidingWindowLimiter
    auth: SlidingWindowLimiter
    expensive: SlidingWindowLimiter
    expensive_ip: SlidingWindowLimiter

    @classmethod
    def from_settings(cls, settings: Settings) -> "RateLimits":
        return cls(
            enabled=settings.rate_limit_enabled,
            api=SlidingWindowLimiter(settings.rate_limit_api_per_min),
            auth=SlidingWindowLimiter(settings.rate_limit_auth_per_min),
            expensive=SlidingWindowLimiter(settings.rate_limit_expensive_per_min),
            expensive_ip=SlidingWindowLimiter(settings.rate_limit_expensive_ip_per_min),
        )


def too_many_requests(retry_after: float) -> JSONResponse:
    seconds = max(math.ceil(retry_after), 1)
    return JSONResponse(
        {"detail": f"Слишком много запросов. Повторите через {seconds} с."},
        status_code=429,
        headers={"Retry-After": str(seconds)},
    )


def client_ip(request: Request) -> str:
    """IP клиента. За reverse proxy берём последний адрес `X-Forwarded-For`: его дописал наш
    proxy, левые значения клиент подделать может, а правый — нет."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def install_rate_limits(app: FastAPI, settings: Settings) -> None:
    """Подключить IP-лимиты (весь API и вход/регистрация) как middleware."""
    limits = RateLimits.from_settings(settings)
    app.state.rate_limits = limits
    api_prefix = settings.api_prefix + "/"
    auth_paths = tuple(settings.api_prefix + path for path in _AUTH_PATHS)

    async def middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        if limits.enabled and path.startswith(api_prefix) and request.method != "OPTIONS":
            ip = client_ip(request)
            if request.method == "POST" and path in auth_paths:
                retry = limits.auth.check(ip)
                if retry is not None:
                    return too_many_requests(retry)
            retry = limits.api.check(ip)
            if retry is not None:
                return too_many_requests(retry)
        return await call_next(request)

    app.middleware("http")(middleware)


async def limit_expensive(request: Request, user: OptionalUserDep) -> None:
    """Зависимость «дорогих» маршрутов: лимит на аккаунт (без auth — на IP) и общий на IP."""
    limits: RateLimits = request.app.state.rate_limits
    if not limits.enabled:
        return
    ip = client_ip(request)
    # Лимит на IP обязателен и для вошедших: иначе его обходят регистрацией новых аккаунтов.
    retry = limits.expensive_ip.check(ip)
    if retry is None:
        retry = limits.expensive.check(f"user:{user.id}" if user else f"ip:{ip}")
    if retry is not None:
        seconds = max(math.ceil(retry), 1)
        raise HTTPException(
            status_code=429,
            detail=f"Слишком много запросов. Повторите через {seconds} с.",
            headers={"Retry-After": str(seconds)},
        )
