"""Курсорная пагинация: курсор — непрозрачная строка с ключом последнего элемента страницы.

Сортировка списков — `updated_at` по убыванию, при равенстве — `id` по убыванию. Ключевой курсор
устойчив к вставкам: новые проекты не сдвигают уже загруженные страницы.
"""

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


class InvalidCursorError(ValueError):
    """Курсор повреждён или получен не от этого API."""


@dataclass(frozen=True, slots=True)
class Cursor:
    updated_at: datetime
    id: UUID

    def encode(self) -> str:
        raw = json.dumps({"u": self.updated_at.isoformat(), "i": str(self.id)})
        return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")

    @classmethod
    def decode(cls, value: str) -> "Cursor":
        try:
            padded = value + "=" * (-len(value) % 4)
            data = json.loads(base64.urlsafe_b64decode(padded.encode()))
            return cls(updated_at=datetime.fromisoformat(data["u"]), id=UUID(data["i"]))
        except (binascii.Error, ValueError, KeyError, TypeError) as error:
            raise InvalidCursorError("Некорректный курсор") from error

    def key(self) -> tuple[datetime, UUID]:
        return (self.updated_at, self.id)
