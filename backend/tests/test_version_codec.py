"""Точность, ограничения и контроль целостности формата версий."""

import hashlib
import random
import struct
import zlib

import pytest

from app.infra.version_codec import MAX_DEPTH, VersionStorageError, pack_xml, unpack_xml


def _large_xml() -> str:
    randomizer = random.Random(42)  # noqa: S311 — воспроизводимые тестовые данные
    text = "".join(chr(randomizer.randrange(32, 127)) for _ in range(8000))
    return f"<definitions><!--{text}--><task name='Привет'/></definitions>"


def test_snapshot_and_delta_restore_exact_utf8_and_preserve_extensions() -> None:
    before = _large_xml()
    after = before.replace("Привет", "🚀 Пока")
    snapshot = pack_xml(before)
    delta = pack_xml(after, before)
    assert snapshot.depth == 0
    assert delta.depth == 1
    assert len(delta.payload) < len(snapshot.payload) / 10
    assert unpack_xml(snapshot.payload, snapshot.sha256) == before
    assert unpack_xml(delta.payload, delta.sha256, previous=before) == after


def test_chain_is_bounded_and_every_revision_restores_exactly() -> None:
    xml = _large_xml()
    depth = 0
    for index in range(MAX_DEPTH * 3):
        changed = xml.replace("<task ", f"<task x='{index}' ", 1)
        packed = pack_xml(changed, xml, previous_depth=depth)
        assert packed.depth <= MAX_DEPTH
        assert (
            unpack_xml(packed.payload, packed.sha256, previous=xml if packed.depth else None)
            == changed
        )
        if depth == MAX_DEPTH:
            assert packed.depth == 0
        xml, depth = changed, packed.depth


@pytest.mark.parametrize(("old", "new"), [("", "abc"), ("abc", ""), ("abc", "xyz"), ("a", "a")])
def test_small_or_unrelated_changes_use_snapshot(old: str, new: str) -> None:
    packed = pack_xml(new, old)
    assert packed.depth == 0
    assert unpack_xml(packed.payload, packed.sha256) == new


def test_corruption_wrong_base_and_unknown_format_are_rejected() -> None:
    before = _large_xml()
    packed = pack_xml(before.replace("Привет", "Пока"), before)
    for payload, digest, base in [
        (packed.payload, packed.sha256, "wrong"),
        (packed.payload, packed.sha256, None),
        (packed.payload[:-2], packed.sha256, before),
        (packed.payload, "0" * 64, before),
        (b"BAD1" + packed.payload[4:], packed.sha256, before),
        (packed.payload + b"extra", packed.sha256, before),
        (b"BVD1" + zlib.compress(struct.pack(">QQ", 999999, 1)), packed.sha256, before),
    ]:
        with pytest.raises(VersionStorageError):
            unpack_xml(payload, digest, previous=base)


def test_snapshot_rejects_invalid_utf8_even_with_matching_hash() -> None:
    data = b"\xff"
    with pytest.raises(VersionStorageError):
        unpack_xml(b"BVS1" + zlib.compress(data), hashlib.sha256(data).hexdigest())


def test_inflate_and_pack_reject_oversized_payloads(monkeypatch) -> None:
    monkeypatch.setattr("app.infra.version_codec.MAX_XML_BYTES", 128)
    with pytest.raises(VersionStorageError):
        pack_xml("x" * 129)
    for data in (b"x" * 129, b"x" * 10000):
        with pytest.raises(VersionStorageError):
            unpack_xml(b"BVS1" + zlib.compress(data), hashlib.sha256(data).hexdigest())
    with pytest.raises(VersionStorageError):
        unpack_xml(b"BVS1invalid-zlib", "0" * 64)
