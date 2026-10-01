"""Хранилище: интерфейсы (`base.py`) и in-memory реализация (`memory.py`)."""

from app.infra.repositories.base import Repositories
from app.infra.repositories.memory import InMemoryStore

__all__ = ["InMemoryStore", "Repositories"]
