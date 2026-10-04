"""Присутствие: несколько вкладок, несколько участников и отключение."""

from uuid import uuid4

import pytest

from app.domain.access import ProjectRole
from app.services.presence import PresenceRegistry, PresentUser


@pytest.mark.asyncio
async def test_presence_deduplicates_tabs_and_broadcasts_departure() -> None:
    registry = PresenceRegistry()
    project_id = uuid4()
    alice = PresentUser(id=uuid4(), email="alice@example.test", role=ProjectRole.EDITOR)
    bob = PresentUser(id=uuid4(), email="bob@example.test", role=ProjectRole.VIEWER)

    first_id, first_queue = await registry.join(project_id, alice)
    assert await first_queue.get() == [alice]
    second_id, second_queue = await registry.join(project_id, alice)
    assert await first_queue.get() == [alice]
    assert await second_queue.get() == [alice]
    third_id, third_queue = await registry.join(project_id, bob)
    assert await first_queue.get() == [alice, bob]
    assert await second_queue.get() == [alice, bob]
    assert await third_queue.get() == [alice, bob]

    await registry.leave(project_id, first_id)
    assert await second_queue.get() == [alice, bob]
    assert await third_queue.get() == [alice, bob]
    await registry.leave(project_id, second_id)
    assert await third_queue.get() == [bob]
    await registry.leave(project_id, third_id)
    assert registry._snapshot(project_id) == []
