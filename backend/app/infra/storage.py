"""Хранилище исходных файлов (документы, аудио) — RFC §4 «uploads»."""

import asyncio
import contextlib
import re
import shutil
import tempfile
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Protocol
from uuid import UUID


class UploadTooLargeError(Exception):
    """Поток загрузки превысил разрешённый размер; частично записанный файл удалён."""

    def __init__(self, limit: int) -> None:
        super().__init__(f"Размер превышает {limit} байт")
        self.limit = limit


type ChunkReader = Callable[[int], Awaitable[bytes]]
_STREAM_CHUNK = 1024 * 1024


class FileStorage(Protocol):
    async def save(self, *, project_id: UUID, file_name: str, data: bytes) -> str:
        """Сохраняет файл и возвращает ключ для `load`/`delete`."""
        ...

    async def save_stream(
        self, *, project_id: UUID, file_name: str, read: ChunkReader, limit: int
    ) -> tuple[str, int]:
        """Пишет поток по кускам (без загрузки целиком в память); `UploadTooLargeError` > limit."""
        ...

    def local_file(self, key: str) -> contextlib.AbstractAsyncContextManager[Path]:
        """Путь к файлу на диске на время блока (для ffmpeg); временная копия удаляется."""
        ...

    async def load(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...


def _suffix(file_name: str) -> str:
    suffix = Path(file_name).suffix.lower()
    return suffix if re.fullmatch(r"\.[a-z0-9]{1,16}", suffix) else ".bin"


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

    async def save_stream(
        self, *, project_id: UUID, file_name: str, read: ChunkReader, limit: int
    ) -> tuple[str, int]:
        chunks: list[bytes] = []
        total = 0
        while chunk := await read(_STREAM_CHUNK):
            total += len(chunk)
            if total > limit:
                raise UploadTooLargeError(limit)
            chunks.append(chunk)
        key = await self.save(project_id=project_id, file_name=file_name, data=b"".join(chunks))
        return key, total

    @asynccontextmanager
    async def local_file(self, key: str) -> AsyncIterator[Path]:
        directory = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="blob-"))
        try:
            path = directory / f"blob{_suffix(key)}"
            await asyncio.to_thread(path.write_bytes, self._files[key])
            yield path
        finally:
            await asyncio.to_thread(shutil.rmtree, directory, True)

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

    async def save_stream(
        self, *, project_id: UUID, file_name: str, read: ChunkReader, limit: int
    ) -> tuple[str, int]:
        suffix = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else "bin"
        key = f"{project_id}/{uuid.uuid4()}.{suffix}"
        path = self._path(key)
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        total = 0
        handle = await asyncio.to_thread(path.open, "wb")
        try:
            while chunk := await read(_STREAM_CHUNK):
                total += len(chunk)
                if total > limit:
                    raise UploadTooLargeError(limit)
                await asyncio.to_thread(handle.write, chunk)
        except BaseException:
            await asyncio.to_thread(handle.close)
            await asyncio.to_thread(path.unlink, missing_ok=True)
            raise
        await asyncio.to_thread(handle.close)
        return key, total

    @asynccontextmanager
    async def local_file(self, key: str) -> AsyncIterator[Path]:
        yield self._path(key)

    async def load(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._path(key).unlink, missing_ok=True)
