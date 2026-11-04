"""Общие HTTP-операции адаптеров: транспорт, разбор ответов и классы ошибок.

Правила SSRF из ADR-0011 действуют на все адаптеры: адрес, введённый пользователем (совместимый
провайдер, произвольный base_url), проверяется `net_guard`, соединение идёт через закреплённый
транспорт, редиректы запрещены. Тело ответа провайдера читается только для классификации
(признак квоты) и никогда не попадает в сообщение пользователю.
"""

from collections.abc import Callable

import httpx

from app.domain.capabilities import CapabilityError, ErrorClass

# Фабрика HTTP-клиента адаптера: (адрес, адрес пользователя?, таймаут) → клиент.
# Собирается в слое сервисов/контейнере, где живут правила SSRF и закрепление IP (ADR-0011):
# слой `ingest` не зависит от `llm`.
type AdapterClientFactory = Callable[[str, bool, float], httpx.AsyncClient]

_BODY_SNIFF_BYTES = 4096
HTTP_ERROR_STATUS = 400
_SERVER_ERROR_STATUS = 500
_AUTH_CODES = frozenset({401, 403})
_QUOTA_CODES = frozenset({402})
_RETRYABLE_CODES = frozenset({408, 425, 429})
_UNSUPPORTED_CODES = frozenset({413, 415, 422})
_TRANSIENT_SERVER_CODES = frozenset({500, 502, 503, 504})
# Признаки исчерпанной квоты в теле ответа: класс важнее кода статуса (429 бывает и лимитом
# частоты, и кончившейся квотой).
_QUOTA_MARKERS = (
    "insufficient_quota",
    "insufficient quota",
    "quota_exceeded",
    "quota exceeded",
    "exceeded your current quota",
    "billing",
)
_AUTH_MARKERS = ("invalid api key", "invalid_api_key", "unauthorized", "authentication")


def provider_client(
    *,
    base_url: str,
    timeout_sec: float,
    guard_host: bool = False,
    transport: httpx.AsyncBaseTransport | None = None,
    client_factory: AdapterClientFactory | None = None,
) -> httpx.AsyncClient:
    """HTTP-клиент адаптера.

    Адреса фиксированных провайдеров доверенные. Адрес пользователя (`guard_host`) проверяет
    `client_factory`: только слой сервисов знает правила SSRF и закрепление IP. Прямое
    создание клиента без фабрики допустимо лишь с подменённым транспортом (тесты адаптера).
    """
    try:
        if client_factory is not None:
            return client_factory(base_url, guard_host, timeout_sec)
        if guard_host and transport is None:
            raise CapabilityError(
                ErrorClass.UNSUPPORTED,
                "Для адреса пользователя нужен клиент с защитой от SSRF",
            )
        return httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout_sec,
            transport=transport,
            follow_redirects=False,
            trust_env=not guard_host,
        )
    except CapabilityError:
        raise
    except (ValueError, httpx.InvalidURL) as error:
        # Проверка SSRF (`UnsafeBaseUrlError` — тоже ValueError) и битый адрес — не 500:
        # это класс `unsupported`, по которому маршрутизатор перейдёт к следующему ключу,
        # а сохранение ключа вернёт пользователю 422.
        raise CapabilityError(
            ErrorClass.UNSUPPORTED,
            f"Адрес провайдера отклонён проверкой безопасности: {error}",
        ) from None


def retry_after(response: httpx.Response) -> float | None:
    """`Retry-After` в секундах без обрезки.

    Обрезать нельзя: при исчерпанной квоте провайдер может просить паузу в час, и именно она
    уходит в `exhausted_until`. Короткий предел действует только на паузы между повторами
    (`RoutingPolicy.max_retry_after_sec`), чтобы прогон не висел.
    """
    value = response.headers.get("Retry-After")
    try:
        seconds = float(value) if value is not None else None
    except ValueError:
        return None
    return seconds if seconds is not None and seconds >= 0 else None


def classify_status(status_code: int, *, body: str) -> ErrorClass:
    """Класс ошибки по коду и (для 4xx) осторожному признаку в теле ответа."""
    lowered = body.lower()
    if status_code in _AUTH_CODES or any(marker in lowered for marker in _AUTH_MARKERS):
        return ErrorClass.AUTH
    if status_code in _QUOTA_CODES or any(marker in lowered for marker in _QUOTA_MARKERS):
        return ErrorClass.QUOTA_EXHAUSTED
    if status_code >= _SERVER_ERROR_STATUS:
        return ErrorClass.TRANSIENT if status_code in _TRANSIENT_SERVER_CODES else ErrorClass.FATAL
    if status_code in _RETRYABLE_CODES:
        return ErrorClass.TRANSIENT
    if status_code in _UNSUPPORTED_CODES:
        return ErrorClass.UNSUPPORTED
    return ErrorClass.FATAL


async def provider_error(response: httpx.Response, *, provider_label: str) -> CapabilityError:
    """Превращает неуспешный ответ в `CapabilityError` без текста провайдера."""
    body = ""
    try:
        raw = await response.aread()
        body = raw[:_BODY_SNIFF_BYTES].decode("utf-8", errors="replace")
    except Exception:
        # Тело нужно только для классификации: ошибка чтения не мешает вернуть класс.
        body = ""
    error_class = classify_status(response.status_code, body=body)
    messages = {
        ErrorClass.AUTH: f"{provider_label} отклонил ключ: проверьте его в настройках",
        ErrorClass.QUOTA_EXHAUSTED: f"У ключа {provider_label} закончилась квота",
        ErrorClass.TRANSIENT: f"{provider_label} временно недоступен: повторите позже",
        ErrorClass.UNSUPPORTED: f"{provider_label} не принимает этот формат материала",
        ErrorClass.FATAL: f"{provider_label} вернул ошибку запроса",
    }
    return CapabilityError(
        error_class,
        messages[error_class],
        retry_after_sec=retry_after(response),
    )
