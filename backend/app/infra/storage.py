"""Хранилище исходных файлов (документы, аудио) — RFC §4 «uploads»."""

import asyncio
import re
import uuid
from pathlib import Path
from typing import Protocol
from uuid import UUID


class FileStorage(Protocol):
    async def save(self, *, project_id: UUID, file_name: str, data: bytes) -> str:
        """Сохраняет файл и возвращает ключ для `load`/`delete`."""
        ...

    async def load(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...


class InMemoryFileStorage:
    def __init__(self) -> None:
        self._files: dict[str, bytes] = {}

    async def save(self, *, project_id: UUID, file_name: str, data: bytes) -> str:
        suffix = Path(file_name).suffix.lower()
        if not re.fullmatch(r"\.[a-z0-9]{1,16}", suffix):
            suffix = ".bin"
        key = f"{project_id}/{uuid.uuid4()}{suffix}"
        self._files[key] = data
        return key

    async def load(self, key: str) -> bytes:
        return self._files[key]

    async def delete(self, key: str) -> None:
        self._files.pop(key, None)


class LocalFileStorage:
    """Хранилище в постоянном volume; ключи не могут выйти за корень данных."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        path = (self._root / key).resolve()
        if not path.is_relative_to(self._root):
            raise ValueError("Недопустимый ключ файла")
        return path

    async def save(self, *, project_id: UUID, file_name: str, data: bytes) -> str:
        suffix = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else "bin"
        key = f"{project_id}/{uuid.uuid4()}.{suffix}"
        path = self._path(key)

        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        await asyncio.to_thread(write)
        return key

    async def load(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._path(key).unlink, missing_ok=True)
