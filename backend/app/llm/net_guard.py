"""Защита от SSRF для адресов совместимых провайдеров, которые вводит пользователь (ADR-0011).

Адрес обязан быть HTTPS (HTTP — только для хоста из `LLM_ALLOWED_PRIVATE_HOSTS`), без учётных
данных в URL, а имя хоста не должно указывать на закрытые сети: loopback, private, link-local
(в т.ч. метаданные облака 169.254.169.254), multicast и зарезервированные диапазоны.
Проверка повторяется перед каждым запросом, переходы по редиректам запрещены.
"""

import asyncio
import ipaddress
import socket
from collections.abc import Iterable
from urllib.parse import urlsplit

_MAX_PORT = 65535
IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class UnsafeBaseUrlError(ValueError):
    """Адрес провайдера не прошёл проверку; сообщение безопасно показывать пользователю."""


def is_public_ip(address: IpAddress) -> bool:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        or getattr(address, "is_site_local", False)
        or (isinstance(address, ipaddress.IPv4Address) and address in _CGNAT)
    )


_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def normalize_base_url(raw: str, *, allowed_private_hosts: Iterable[str] = ()) -> str:
    """Проверяет форму адреса и возвращает его без хвостового `/`."""
    allowed = {host.lower() for host in allowed_private_hosts}
    value = raw.strip()
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        raise UnsafeBaseUrlError("Некорректный адрес провайдера") from None
    if parsed.scheme not in {"http", "https"} or not host:
        raise UnsafeBaseUrlError("Адрес провайдера должен начинаться с https://")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise UnsafeBaseUrlError("В адресе провайдера не должно быть логина, параметров и якоря")
    if parsed.scheme == "http" and host not in allowed:
        raise UnsafeBaseUrlError("Адрес провайдера должен начинаться с https://")
    if port is not None and not 1 <= port <= _MAX_PORT:
        raise UnsafeBaseUrlError("Некорректный порт адреса провайдера")
    return value.rstrip("/")


async def resolve_public_addresses(
    host: str, port: int, *, allowed_private_hosts: Iterable[str] = ()
) -> list[IpAddress]:
    """Разрешает имя хоста и отклоняет закрытые адреса, если хост не в явном списке.

    Возвращает проверенные адреса: именно к ним и надо подключаться (иначе повторное разрешение
    имени при соединении позволит подменить ответ DNS между проверкой и запросом).
    """
    host = host.lower()
    allowed = {item.lower() for item in allowed_private_hosts}
    try:
        literal: IpAddress | None = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        addresses: list[IpAddress] = [literal]
    else:
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(
                host, port, type=socket.SOCK_STREAM
            )
        except OSError:
            raise UnsafeBaseUrlError("Не удалось найти адрес провайдера") from None
        addresses = [ipaddress.ip_address(info[4][0]) for info in infos]
    if host in allowed:
        return addresses
    if not addresses or not all(is_public_ip(address) for address in addresses):
        raise UnsafeBaseUrlError(
            "Адрес провайдера указывает на закрытую сеть. Для локальной модели администратор "
            "должен добавить хост в LLM_ALLOWED_PRIVATE_HOSTS"
        )
    return addresses


async def ensure_public_host(base_url: str, *, allowed_private_hosts: Iterable[str] = ()) -> None:
    """Предварительная проверка адреса: понятная ошибка до запроса."""
    parsed = urlsplit(base_url)
    host = (parsed.hostname or "").lower()
    if host in {item.lower() for item in allowed_private_hosts}:
        return
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    await resolve_public_addresses(host, port, allowed_private_hosts=allowed_private_hosts)
