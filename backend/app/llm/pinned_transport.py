"""HTTP-транспорт, который подключается к проверенному IP, а не к повторно разрешённому имени.

Закрывает DNS rebinding (ADR-0011): `net_guard` проверяет адреса и тут же отдаёт их сокету,
поэтому между проверкой и соединением нет второго запроса к DNS. Имя хоста остаётся в URL, так что
заголовок Host, SNI и проверка сертификата работают по имени провайдера.
"""

from collections.abc import Awaitable, Callable, Iterable, Sequence
from typing import Any

import httpcore
import httpx

from app.llm.net_guard import IpAddress, resolve_public_addresses

Resolver = Callable[[str, int], Awaitable[Sequence[IpAddress]]]


class PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """Разрешает имя через guard и пробует проверенные адреса по очереди."""

    def __init__(
        self,
        *,
        allowed_private_hosts: Iterable[str] = (),
        resolver: Resolver | None = None,
        backend: httpcore.AsyncNetworkBackend | None = None,
    ) -> None:
        self._allowed = tuple(allowed_private_hosts)
        self._resolver = resolver
        self._backend = backend or httpcore.AnyIOBackend()

    async def _resolve(self, host: str, port: int) -> Sequence[IpAddress]:
        if self._resolver is not None:
            return await self._resolver(host, port)
        return await resolve_public_addresses(host, port, allowed_private_hosts=self._allowed)

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 — сигнатура httpcore
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        addresses = await self._resolve(host, port)
        error: Exception | None = None
        for address in addresses:
            try:
                return await self._backend.connect_tcp(
                    str(address),
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except httpcore.ConnectError as exc:
                error = exc
        raise error or httpcore.ConnectError("Нет проверенных адресов для подключения")

    async def connect_unix_socket(self, *_args: Any, **_kwargs: Any) -> httpcore.AsyncNetworkStream:
        raise httpcore.ConnectError("Unix-сокеты запрещены")

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


def pinned_transport(
    *, allowed_private_hosts: Iterable[str] = (), resolver: Resolver | None = None
) -> httpx.AsyncHTTPTransport:
    """Штатный транспорт httpx с подменённым сетевым бэкендом пула соединений."""
    transport = httpx.AsyncHTTPTransport(retries=0)
    # Публичного параметра `network_backend` у httpx нет; версия httpx зафиксирована в uv.lock,
    # а тест проверяет, что подмена действительно работает.
    transport._pool = httpcore.AsyncConnectionPool(
        ssl_context=httpx.create_ssl_context(),
        max_connections=100,
        max_keepalive_connections=20,
        keepalive_expiry=5.0,
        network_backend=PinnedNetworkBackend(
            allowed_private_hosts=allowed_private_hosts, resolver=resolver
        ),
    )
    return transport
