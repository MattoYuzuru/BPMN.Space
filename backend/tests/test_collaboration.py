"""Проверки протокола live-комнаты и контроля конфликтующих сохранений."""

from datetime import UTC, datetime, timedelta
from typing import get_args, get_type_hints
from uuid import UUID

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.v1.collaboration import PresenceUpdate
from app.api.v1.presence import project_presence
from app.api.v1.runs import run_events
from app.domain.access import ProjectRole
from app.fixtures import read_bpmn
from app.infra.seed import DEMO_PROJECT_ID
from app.services.collaboration import RealtimeHub, RoomFullError
from app.services.errors import StaleVersionError

API = "/api/v1"


def test_sse_auth_dependencies_release_database_session_before_streaming() -> None:
    """Долгоживущий SSE не должен удерживать DB-сессию до отключения клиента."""
    for endpoint in (project_presence, run_events):
        annotation = get_type_hints(endpoint, include_extras=True)["user"]
        dependency = next(item for item in get_args(annotation) if hasattr(item, "scope"))
        assert dependency.scope == "function"


def test_presence_message_rejects_unknown_fields_and_non_finite_coordinates() -> None:
    for message in (
        {
            "type": "presence.update",
            "protocol_version": 1,
            "cursor": {"x": float("nan"), "y": 0},
        },
        {"type": "presence.update", "protocol_version": 1, "user_id": "spoofed"},
    ):
        try:
            PresenceUpdate.model_validate(message)
        except ValidationError:
            continue
        raise AssertionError("Некорректное сообщение прошло валидацию")


async def test_ticket_is_project_bound_and_single_use() -> None:
    hub = RealtimeHub()
    project_id = UUID(int=1)
    other_project_id = UUID(int=2)
    raw = hub.issue_ticket(
        project_id=project_id,
        role=ProjectRole.OWNER,
        user_id=None,
        display_name="Гость",
    )

    assert hub.consume_ticket(raw, project_id=other_project_id) is None
    assert hub.consume_ticket(raw, project_id=project_id) is None


async def test_room_broadcasts_presence_and_cleans_up() -> None:
    hub = RealtimeHub()
    project_id = UUID(int=1)
    owner = hub.issue_ticket(
        project_id=project_id,
        role=ProjectRole.OWNER,
        user_id=None,
        display_name="Тимофей",
    )
    viewer = hub.issue_ticket(
        project_id=project_id,
        role=ProjectRole.VIEWER,
        user_id=None,
        display_name="Гость",
        share_link_id=UUID(int=3),
    )
    owner_ticket = hub.consume_ticket(owner, project_id=project_id)
    viewer_ticket = hub.consume_ticket(viewer, project_id=project_id)
    assert owner_ticket is not None
    assert viewer_ticket is not None
    first = await hub.join(project_id, owner_ticket)
    second = await hub.join(project_id, viewer_ticket)
    await first.queue.get()  # первый snapshot
    await second.queue.get()  # snapshot после входа viewer
    await first.queue.get()  # тот же snapshot доставлен первому участнику

    await hub.update_presence(
        first,
        cursor={"x": 42.0, "y": 21.0},
        selection=["Task_1"],
        activity="editing",
        drag={"element_ids": ["Task_1"], "start": {"x": 0, "y": 0}, "current": {"x": 2, "y": 3}},
    )
    update = await second.queue.get()
    assert update["type"] == "presence.changed"
    participant = update["participant"]
    assert isinstance(participant, dict)
    assert participant["display_name"] == "Тимофей"
    assert participant["cursor"] == {"x": 42.0, "y": 21.0}
    assert participant["drag"]["current"] == {"x": 2, "y": 3}

    await hub.leave(first)
    assert [person["display_name"] for person in await hub.snapshot(project_id)] == ["Гость"]
    await hub.leave(second)
    assert await hub.snapshot(project_id) == []


async def test_released_drag_stays_until_saved_version_then_clears() -> None:
    hub = RealtimeHub()
    project_id = UUID(int=20)
    participants = []
    for name in ("Редактор", "Наблюдатель"):
        raw = hub.issue_ticket(
            project_id=project_id,
            role=ProjectRole.OWNER if name == "Редактор" else ProjectRole.VIEWER,
            user_id=None,
            display_name=name,
        )
        ticket = hub.consume_ticket(raw, project_id=project_id)
        assert ticket is not None
        participants.append(await hub.join(project_id, ticket))
    editor, viewer = participants
    while not editor.queue.empty():
        editor.queue.get_nowait()
    while not viewer.queue.empty():
        viewer.queue.get_nowait()

    drag = {
        "element_ids": ["Task_1"],
        "start": {"x": 10.0, "y": 20.0},
        "current": {"x": 40.0, "y": 60.0},
        "phase": "released",
    }
    await hub.update_presence(
        editor, cursor=None, selection=["Task_1"], activity="editing", drag=drag
    )
    await viewer.queue.get()  # presence.changed with drag preview
    await hub.update_presence(editor, cursor=None, selection=["Task_1"], activity="idle", drag=None)
    retained = await viewer.queue.get()
    assert retained["participant"]["drag"] == drag

    await hub.publish(project_id, {"type": "diagram.version", "version_id": "v2"})
    snapshot = await viewer.queue.get()
    assert snapshot["type"] == "presence.snapshot"
    assert snapshot["participants"][0]["drag"] is None
    assert (await viewer.queue.get())["type"] == "diagram.version"


async def test_ticket_expiry_and_room_connection_cap() -> None:
    hub = RealtimeHub()
    project_id = UUID(int=1)
    now = datetime(2026, 10, 5, tzinfo=UTC)
    raw = hub.issue_ticket(
        project_id=project_id,
        role=ProjectRole.OWNER,
        user_id=UUID(int=5),
        display_name="Тимофей",
        now=now,
    )
    assert hub.consume_ticket(raw, project_id=project_id, now=now + timedelta(minutes=2)) is None

    for _ in range(3):
        ticket = hub.issue_ticket(
            project_id=project_id,
            role=ProjectRole.OWNER,
            user_id=UUID(int=5),
            display_name="Тимофей",
        )
        principal = hub.consume_ticket(ticket, project_id=project_id)
        assert principal is not None
        await hub.join(project_id, principal)
    last = hub.issue_ticket(
        project_id=project_id,
        role=ProjectRole.OWNER,
        user_id=UUID(int=5),
        display_name="Тимофей",
    )
    principal = hub.consume_ticket(last, project_id=project_id)
    assert principal is not None
    try:
        await hub.join(project_id, principal)
    except RoomFullError:
        pass
    else:
        raise AssertionError("Лимит соединений пользователя не сработал")


def test_websocket_ticket_and_presence_flow(client: TestClient) -> None:
    project_id = str(DEMO_PROJECT_ID)
    ticket = client.post(f"{API}/projects/{project_id}/collaboration-ticket").json()["ticket"]
    with client.websocket_connect(
        f"{API}/projects/{project_id}/collaboration/ws",
        subprotocols=["bpmn.collaboration.v1", f"bpmn.ticket.{ticket}"],
    ) as socket:
        assert socket.accepted_subprotocol == "bpmn.collaboration.v1"
        ready = socket.receive_json()
        assert ready["type"] == "ready"
        assert ready["participants"][0]["role"] == "owner"
        socket.receive_json()  # presence.snapshot
        socket.send_json(
            {
                "type": "presence.update",
                "protocol_version": 1,
                "cursor": {"x": 12, "y": 18},
                "selection": ["Task_1"],
                "activity": "editing",
                "drag": {
                    "element_ids": ["Task_1"],
                    "start": {"x": 10, "y": 20},
                    "current": {"x": 30, "y": 50},
                },
            }
        )
        event = socket.receive_json()
        assert event["type"] == "presence.changed"
        assert event["participant"]["cursor"] == {"x": 12, "y": 18}
        assert event["participant"]["drag"]["current"] == {"x": 30, "y": 50}
        socket.close()


def test_stale_version_error_contains_current_head() -> None:
    head = UUID(int=7)
    error = StaleVersionError(head, 4)
    assert error.head_version_id == head
    assert error.head_version_number == 4


def test_manual_save_rejects_stale_base_without_creating_a_version(client: TestClient) -> None:
    project_id = str(DEMO_PROJECT_ID)
    initial = client.get(f"{API}/projects/{project_id}").json()["latest_version"]
    saved = client.put(
        f"{API}/projects/{project_id}/diagram",
        json={
            "xml": read_bpmn("tp861_v2").replace("Провести выездной осмотр", "Осмотр"),
            "base_version_id": initial["id"],
        },
    )
    assert saved.status_code == 201, saved.text
    stale = client.put(
        f"{API}/projects/{project_id}/diagram",
        json={"xml": read_bpmn("tp861_v2"), "base_version_id": initial["id"]},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "stale_version"
    assert stale.json()["head_version_id"] == saved.json()["id"]
    assert stale.json()["head_version_number"] == saved.json()["number"]
