"""Хранилище исходных файлов (документы, аудио) — RFC §4 «uploads».

TODO(real): #6 файлы в docker volume `/data/uploads/<project_id>/<uuid>` (путь из config.py),
позже S3 за этим же интерфейсом; удаление файлов вместе с проектом.
"""

import uuid
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
        suffix = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else "bin"
        key = f"{project_id}/{uuid.uuid4()}.{suffix}"
        self._files[key] = data
        return key

    async def load(self, key: str) -> bytes:
        return self._files[key]

    async def delete(self, key: str) -> None:
        self._files.pop(key, None)
