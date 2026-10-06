"""Версионированное хранение XML: сжатый снимок или точная замена диапазона байтов.

Формат не зависит от bpmn-js и сохраняет XML побайтно, включая неизвестные расширения.
Цепочка ограничена; изменение, которое плохо сжимается как дельта, становится снимком.
"""

import hashlib
import struct
import zlib
from dataclasses import dataclass

MAX_DEPTH = 20
MAX_MAINTENANCE_BATCH = 1000
MAX_XML_BYTES = 64 * 1024 * 1024
MIN_DELTA_SAVING = 128
_HEADER = struct.Struct(">QQ")
_SNAPSHOT = b"BVS1"
_DELTA = b"BVD1"


class VersionStorageError(RuntimeError):
    """Повреждение хранилища: возвращать непроверенный XML запрещено."""


@dataclass(frozen=True)
class PackedVersion:
    payload: bytes
    sha256: str
    depth: int


def pack_xml(xml: str, previous: str | None = None, *, previous_depth: int = 0) -> PackedVersion:
    data = xml.encode("utf-8")
    if len(data) > MAX_XML_BYTES:
        raise VersionStorageError("XML превышает ограничение формата хранения")
    digest = hashlib.sha256(data).hexdigest()
    snapshot = _SNAPSHOT + zlib.compress(data)
    if previous is None or previous_depth >= MAX_DEPTH:
        return PackedVersion(snapshot, digest, 0)
    old = previous.encode("utf-8")
    start = 0
    common = min(len(old), len(data))
    while start < common and old[start] == data[start]:
        start += 1
    suffix = 0
    while suffix < common - start and old[-suffix - 1] == data[-suffix - 1]:
        suffix += 1
    old_end = len(old) - suffix
    new_end = len(data) - suffix
    delta = _DELTA + zlib.compress(_HEADER.pack(start, old_end - start) + data[start:new_end])
    # UUID базы и служебные поля тоже занимают место: маленькую экономию не принимаем.
    if len(delta) + MIN_DELTA_SAVING < len(snapshot):
        return PackedVersion(delta, digest, previous_depth + 1)
    return PackedVersion(snapshot, digest, 0)


def _inflate(payload: bytes) -> bytes:
    decoder = zlib.decompressobj()
    try:
        data = decoder.decompress(payload, MAX_XML_BYTES + _HEADER.size + 1)
    except zlib.error as error:
        raise VersionStorageError("Повреждены сжатые данные версии") from error
    if not decoder.eof or decoder.unused_data or len(data) > MAX_XML_BYTES + _HEADER.size:
        raise VersionStorageError("Некорректный размер или окончание данных версии")
    return data


def unpack_xml(payload: bytes, sha256: str, *, previous: str | None = None) -> str:
    kind = payload[:4]
    data = _inflate(payload[4:])
    if kind == _DELTA:
        if previous is None or len(data) < _HEADER.size:
            raise VersionStorageError("У дельты нет корректной базы")
        old = previous.encode("utf-8")
        start, removed = _HEADER.unpack_from(data)
        if start > len(old) or removed > len(old) - start:
            raise VersionStorageError("Дельта выходит за границы базовой версии")
        data = old[:start] + data[_HEADER.size :] + old[start + removed :]
    elif kind != _SNAPSHOT or previous is not None:
        raise VersionStorageError("Неизвестный формат или некорректная база снимка")
    if len(data) > MAX_XML_BYTES or hashlib.sha256(data).hexdigest() != sha256:
        raise VersionStorageError("Контрольная сумма версии не совпадает")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise VersionStorageError("Версия не является UTF-8 XML") from error
