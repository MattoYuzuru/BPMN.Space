"""Ссылка проверки коллеги (RFC-0007, шаг 3): роль reviewer, область, промпт, токен, журнал.

HTTP-сценарии с авторизацией и PostgreSQL (фикстура `stack` из `test_auth_http`, временная
схема); без TEST_DATABASE_URL они пропускаются (см. `make test-postgres`). MCP-клиент берётся
из `test_mcp`: агент проверяющего ходит в тот же `/mcp`, что и остальные агенты.
"""

# Фикстура `stack` импортируется из test_auth_http: параметры тестов её «переопределяют».
# ruff: noqa: F811

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import create_async_engine

from app.domain.bpmn.document import parse_bpmn
from app.domain.models import (
    Question,
    QuestionCategory,
    QuestionKind,
    QuestionStatus,
    Severity,
)
from app.infra.db_models import ProjectShareLinkRow
from tests.test_api_tokens_http import Agent
from tests.test_auth_http import (  # noqa: F401 — фикстура `stack` подключается импортом
    MIGRATIONS_DIR,
    Account,
    Stack,
    _finished_project,
    stack,
)
from tests.test_mcp import _call, _error, _mcp_server, _payload

pytestmark = pytest.mark.asyncio
PERSONAL_TOKEN_NAME = "Claude Code на ноутбуке"  # noqa: S105 — название токена, не секрет


# ---------- вспомогательные ----------


async def _lanes(owner: Account, project_id: str) -> tuple[dict[str, str], dict[str, str]]:
    """Дорожки схемы и привязка узлов к дорожкам (id дорожки → название)."""
    detail = (await owner.get(f"/projects/{project_id}")).json()
    version = detail["latest_version"]
    xml = (await owner.get(f"/versions/{version['id']}")).json()["xml"]
    document = parse_bpmn(xml)
    lane_by_id = {lane.id: lane.name for lane in document.lanes}
    element_lane = {
        node.id: node.lane_id for node in document.nodes.values() if node.lane_id is not None
    }
    return lane_by_id, element_lane


async def _review_link(
    owner: Account, project_id: str, lane_ids: list[str], **body: object
) -> dict[str, object]:
    response = await owner.post(
        f"/projects/{project_id}/share-links",
        json={"role": "reviewer", "lane_ids": lane_ids, **body},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _secret(url_path: str) -> str:
    return url_path.rsplit("/", 1)[-1]


async def _agent_token(account: Account, share_secret: str) -> dict[str, object]:
    response = await account.post(f"/shares/{share_secret}/agent-token")
    assert response.status_code == 201, response.text
    return response.json()


async def _add_question(
    stack: Stack,
    project_id: str,
    *,
    code: str,
    element_ids: list[str],
    status: QuestionStatus = QuestionStatus.OPEN,
) -> Question:
    repos = stack.database.store.repositories()
    now = datetime.now(UTC)
    question = Question(
        id=uuid4(),
        project_id=UUID(project_id),
        code=code,
        kind=QuestionKind.MISSING_ACTOR,
        severity=Severity.MAJOR,
        status=status,
        text=f"Вопрос проверки {code}: кто согласует?",
        assumption="Согласует руководитель",
        created_at=now,
        updated_at=now,
        element_ids=list(element_ids),
        category=QuestionCategory.BUSINESS,
    )
    await repos.questions.add(question)
    return question


async def _scope_fixture(stack: Stack, owner: Account, finished: dict[str, Any]) -> dict[str, Any]:
    """Проект с проверяемой областью: выбранная дорожка, вопросы внутри и вне неё."""
    project_id = str(finished["project"])
    lane_by_id, element_lane = await _lanes(owner, project_id)
    assert len(lane_by_id) >= 2, "для проверки области нужны минимум две дорожки"
    lanes = list(lane_by_id)
    scoped_lane = lanes[0]
    outside_lane = lanes[1]
    node_in_scope = next(
        (element for element, lane in element_lane.items() if lane == scoped_lane), scoped_lane
    )
    inside = await _add_question(stack, project_id, code="Q-901", element_ids=[node_in_scope])
    inside_second = await _add_question(
        stack, project_id, code="Q-902", element_ids=[node_in_scope]
    )
    outside = await _add_question(stack, project_id, code="Q-903", element_ids=[outside_lane])
    link = await _review_link(owner, project_id, [scoped_lane])
    return {
        "project_id": project_id,
        "scoped_lane": scoped_lane,
        "scoped_lane_name": lane_by_id[scoped_lane],
        "outside_lane": outside_lane,
        "inside": inside,
        "inside_second": inside_second,
        "outside": outside,
        "link": link,
        "secret": _secret(str(link["url_path"])),
    }


# ---------- схема БД ----------


async def test_migration_0023_adds_reviewer_role_and_drops_it_on_downgrade() -> None:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL не задан; PostgreSQL-интеграционный тест пропущен")
    schema = f"test_{uuid4().hex}"
    admin = create_async_engine(url)
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))

    def migrate(action: Any) -> Any:
        def run(connection: object) -> None:
            config.attributes["connection"] = connection
            action(config)

        return run

    user_id, project_id, link_id = uuid4(), uuid4(), uuid4()
    try:
        async with engine.begin() as connection:
            # Проверяем саму 0023 в её ветке: после неё есть 0024/0025 других волн.
            await connection.run_sync(
                migrate(lambda cfg: command.upgrade(cfg, "0023_reviewer_role"))
            )
            role_check = await connection.scalar(
                text(
                    "select pg_get_constraintdef(oid) from pg_constraint "
                    "where conname = 'ck_project_share_links_role' and "
                    "conrelid = 'project_share_links'::regclass"
                )
            )
            assert role_check is not None
            assert "reviewer" in role_check
            on_delete = await connection.scalar(
                text(
                    "select confdeltype from pg_constraint where "
                    "conname = 'fk_api_tokens_share_link_id' and "
                    "conrelid = 'api_tokens'::regclass"
                )
            )
            # CASCADE: токен проверки умирает вместе со ссылкой, а не становится обычным.
            assert on_delete in {b"c", "c"}
            indexes = {
                row[0]
                for row in await connection.execute(
                    text("select indexname from pg_indexes where schemaname = :schema"),
                    {"schema": schema},
                )
            }
            assert "ix_api_tokens_share_link_id" in indexes
            assert "ix_questions_answer_share_link_id" in indexes
            await connection.execute(
                text(
                    "INSERT INTO users (id, email, hashed_password, is_active, is_superuser, "
                    "is_verified) VALUES (:id, 'reviewer@example.com', 'x', true, false, false)"
                ),
                {"id": user_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO projects (id, title, created_at, updated_at, owner_id, "
                    "public_read_only) VALUES (:id, 'Проверка', now(), now(), :owner, false)"
                ),
                {"id": project_id, "owner": user_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO project_share_links (id, project_id, token_hash, role, "
                    "created_by, created_at, lane_ids) VALUES (:id, :project, :hash, "
                    "'reviewer', :owner, now(), '[\"Lane_1\"]'::jsonb)"
                ),
                {"id": link_id, "project": project_id, "hash": "a" * 64, "owner": user_id},
            )
            await connection.run_sync(
                migrate(lambda cfg: command.downgrade(cfg, "0022_merge_wave2_heads"))
            )
            downgraded = (
                await connection.execute(
                    text("select role, revoked_at from project_share_links where id = :id"),
                    {"id": link_id},
                )
            ).one()
            # Откат гасит ссылку проверки, а не понижает её до просмотра всего проекта.
            assert downgraded[0] == "viewer"
            assert downgraded[1] is not None
            columns = await connection.execute(
                text(
                    "select column_name from information_schema.columns where "
                    "table_schema = :schema and table_name = 'project_share_links'"
                ),
                {"schema": schema},
            )
            assert "lane_ids" not in {row[0] for row in columns}
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


# ---------- создание ссылки и область ----------


async def test_reviewer_link_validates_lanes_and_old_links_still_work(stack: Stack) -> None:
    owner = await stack.user("review-owner@example.com")
    finished = await _finished_project(owner)
    project_id = str(finished["project"])
    lane_by_id, _ = await _lanes(owner, project_id)
    lane_id = next(iter(lane_by_id))

    invalid = await owner.post(
        f"/projects/{project_id}/share-links",
        json={"role": "reviewer", "lane_ids": ["Lane_does_not_exist"]},
    )
    assert invalid.status_code == 422
    assert "Дорожка" in invalid.json()["detail"]

    created = await _review_link(owner, project_id, [lane_id])
    assert created["role"] == "reviewer"
    assert created["lane_ids"] == [lane_id]
    listed = (await owner.get(f"/projects/{project_id}/share-links")).json()
    assert listed[0]["lane_ids"] == [lane_id]

    scoped_without_lanes = await owner.post(
        f"/projects/{project_id}/share-links", json={"role": "reviewer"}
    )
    assert scoped_without_lanes.status_code == 201
    assert scoped_without_lanes.json()["lane_ids"] == []

    # Старые ссылки не сломались; область дорожек им задавать нельзя.
    viewer = await owner.post(f"/projects/{project_id}/share-links", json={"role": "viewer"})
    assert viewer.status_code == 201
    assert viewer.json()["lane_ids"] == []
    wrong_role = await owner.post(
        f"/projects/{project_id}/share-links",
        json={"role": "viewer", "lane_ids": [lane_id]},
    )
    assert wrong_role.status_code == 422


async def test_reviewer_share_filters_questions_to_lane_scope(stack: Stack) -> None:
    owner = await stack.user("review-scope@example.com")
    finished = await _finished_project(owner)
    scope = await _scope_fixture(stack, owner, finished)
    project_id = scope["project_id"]
    secret = scope["secret"]

    shared = await (await stack.guest()).get(f"/shares/{secret}")
    assert shared.status_code == 200, shared.text
    body = shared.json()
    assert body["role"] == "reviewer"
    assert body["scope"] == {
        "lane_ids": [scope["scoped_lane"]],
        "lanes": [scope["scoped_lane_name"]],
        "whole_project": False,
    }
    codes = {question["code"] for question in body["detail"]["questions"]}
    assert "Q-901" in codes
    assert "Q-902" in codes
    assert "Q-903" not in codes  # вопрос чужой дорожки не виден
    assert body["detail"]["access"] == "reviewer"

    questions = await (await stack.guest()).get(f"/shares/{secret}/questions")
    assert questions.status_code == 200
    listed = {question["code"] for question in questions.json()}
    assert "Q-901" in listed
    assert "Q-903" not in listed

    # Ссылка просмотра показывает проект целиком — совместимость сохранена.
    viewer_link = await owner.post(f"/projects/{project_id}/share-links", json={"role": "viewer"})
    viewer_shared = await (await stack.guest()).get(
        f"/shares/{_secret(viewer_link.json()['url_path'])}"
    )
    assert viewer_shared.json()["scope"]["whole_project"] is True
    viewer_codes = {question["code"] for question in viewer_shared.json()["detail"]["questions"]}
    assert "Q-903" in viewer_codes

    # Ссылка проверки не добавляет проект в профиль.
    stranger = await stack.user("review-accept@example.com")
    accepted = await stranger.post(f"/shares/{secret}/accept")
    assert accepted.status_code == 403


async def test_agent_prompt_has_scope_questions_and_no_secret(stack: Stack) -> None:
    owner = await stack.user("review-prompt@example.com")
    finished = await _finished_project(owner)
    scope = await _scope_fixture(stack, owner, finished)
    secret = scope["secret"]

    prompt = await (await stack.guest()).get(f"/shares/{secret}/agent-prompt")
    assert prompt.status_code == 200, prompt.text
    body = prompt.json()
    text = body["text"]
    assert str(scope["scoped_lane_name"]) in text
    assert "Q-901" in text
    assert "Q-903" not in text
    assert secret not in text  # секрет ссылки в промпт не попадает
    assert any(item["code"] == "Q-901" for item in body["questions_recap"])
    assert body["lane_ids"] == [scope["scoped_lane"]]
    assert body["whole_project"] is False

    # Промпт — сценарий проверки: у viewer и editor его нет (403).
    viewer_link = await owner.post(
        f"/projects/{finished['project']}/share-links", json={"role": "viewer"}
    )
    viewer_prompt = await (await stack.guest()).get(
        f"/shares/{_secret(viewer_link.json()['url_path'])}/agent-prompt"
    )
    assert viewer_prompt.status_code == 403
    editor_link = await owner.post(
        f"/projects/{finished['project']}/share-links", json={"role": "editor"}
    )
    editor_prompt = await (await stack.guest()).get(
        f"/shares/{_secret(editor_link.json()['url_path'])}/agent-prompt"
    )
    assert editor_prompt.status_code == 403


# ---------- токен агента, права и отзыв ----------


async def test_agent_token_grants_scoped_read_and_answers(stack: Stack) -> None:
    owner = await stack.user("review-token-owner@example.com")
    finished = await _finished_project(owner)
    scope = await _scope_fixture(stack, owner, finished)
    project_id = scope["project_id"]
    secret = scope["secret"]
    link_id = scope["link"]["id"]

    stranger = await stack.user("review-token-stranger@example.com")
    issued = await _agent_token(stranger, secret)
    token_secret = str(issued["secret"])
    assert token_secret.startswith("bps_")
    assert issued["scopes"] == ["projects:read", "questions:answer"]
    assert issued["project_id"] == project_id
    assert issued["lane_ids"] == [scope["scoped_lane"]]
    assert str(issued["mcp_url"]).endswith("/mcp")
    assert token_secret in str(issued["command"])
    assert "claude mcp add" in str(issued["command"])

    agent = Agent(stack, token_secret)
    detail = await agent.get(f"/projects/{project_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["access"] == "reviewer"
    codes = {question["code"] for question in detail.json()["questions"]}
    assert "Q-901" in codes
    assert "Q-903" not in codes

    answered = await agent.post(
        f"/questions/{scope['inside'].id}/answer",
        json={"text": "Согласует начальник отдела"},
    )
    assert answered.status_code == 200, answered.text
    answer = answered.json()["answer"]
    assert answer["via"] == "agent"
    assert answer["via_name"] == issued["name"]
    assert answer["share_link_id"] == link_id

    outside = await agent.post(
        f"/questions/{scope['outside'].id}/answer", json={"text": "Не моя дорожка"}
    )
    assert outside.status_code == 404  # вне области — как чужой вопрос

    # Проверяющий не меняет проект и источники: прав на запись у токена ссылки нет.
    source = await agent.post(
        f"/projects/{project_id}/sources/text", json={"content": "Новый материал"}
    )
    assert source.status_code == 403
    patch = await agent.request("PATCH", f"/projects/{project_id}", json={"title": "Новое имя"})
    assert patch.status_code == 403
    diagram = await agent.request(
        "PUT",
        f"/projects/{project_id}/diagram",
        json={"xml": str(finished["xml"]), "base_version_id": str(finished["version"])},
    )
    assert diagram.status_code == 403

    # Ссылка просмотра токен агента не выдаёт: читать она даёт, отвечать — нет.
    viewer_link = await owner.post(f"/projects/{project_id}/share-links", json={"role": "viewer"})
    viewer_secret = _secret(viewer_link.json()["url_path"])
    viewer_issue = await stranger.post(f"/shares/{viewer_secret}/agent-token")
    assert viewer_issue.status_code == 403

    # Гость токен не получает.
    anonymous = await (await stack.guest()).post(f"/shares/{secret}/agent-token")
    assert anonymous.status_code == 401


async def test_revoked_or_expired_link_closes_review_token(stack: Stack) -> None:
    owner = await stack.user("review-revoke-owner@example.com")
    finished = await _finished_project(owner)
    scope = await _scope_fixture(stack, owner, finished)
    project_id = scope["project_id"]
    secret = scope["secret"]
    stranger = await stack.user("review-revoke-stranger@example.com")
    issued = await _agent_token(stranger, secret)
    agent = Agent(stack, str(issued["secret"]))

    assert (await agent.get(f"/projects/{project_id}")).status_code == 200
    revoked = await owner.delete(f"/projects/{project_id}/share-links/{scope['link']['id']}")
    assert revoked.status_code == 204
    # Отзыв ссылки мгновенно закрывает токен: тот же 401, что у отозванного токена.
    assert (await agent.get(f"/projects/{project_id}")).status_code == 401
    assert (await agent.get("/auth/me")).status_code == 401
    assert (await stranger.post(f"/shares/{secret}/agent-token")).status_code == 404

    # Истечение ссылки закрывает доступ так же.
    second_owner = await stack.user("review-expire@example.com")
    second = await _finished_project(second_owner)
    second_scope = await _scope_fixture(stack, second_owner, second)
    second_token = await _agent_token(stranger, str(second_scope["secret"]))
    second_agent = Agent(stack, str(second_token["secret"]))
    assert (await second_agent.get(f"/projects/{second_scope['project_id']}")).status_code == 200
    now = datetime.now(UTC)
    async with stack.database.sessions.begin() as session:
        # CHECK `expires_at > created_at`: сдвигаем окно ссылки в прошлое, а не только срок.
        await session.execute(
            update(ProjectShareLinkRow)
            .where(ProjectShareLinkRow.id == UUID(str(second_scope["link"]["id"])))
            .values(created_at=now - timedelta(days=2), expires_at=now - timedelta(days=1))
        )
    assert (await second_agent.get(f"/projects/{second_scope['project_id']}")).status_code == 401


# ---------- MCP: проверяющий агент ----------


async def test_mcp_review_token_is_scoped_and_can_answer(stack: Stack) -> None:
    owner = await stack.user("review-mcp-owner@example.com")
    finished = await _finished_project(owner)
    scope = await _scope_fixture(stack, owner, finished)
    project_id = scope["project_id"]
    stranger = await stack.user("review-mcp-stranger@example.com")
    issued = await _agent_token(stranger, str(scope["secret"]))
    async with _mcp_server(stack) as connect:
        session = await connect(str(issued["secret"]))
        projects = _payload(await _call(session, "list_projects"))
        card = next(item for item in projects["items"] if item["id"] == project_id)
        assert card["access"] == "reviewer"

        detail = _payload(await _call(session, "get_project", {"project_id": project_id}))
        codes = {question["code"] for question in detail["questions"]}
        assert "Q-901" in codes
        assert "Q-903" not in codes

        listed = _payload(await _call(session, "list_questions", {"project_id": project_id}))
        listed_codes = {question["code"] for question in listed["items"]}
        assert {"Q-901", "Q-902"} & listed_codes
        assert "Q-903" not in listed_codes

        answered = _payload(
            await _call(
                session,
                "answer_question",
                {"question_id": str(scope["inside_second"].id), "text": "Ответ проверяющего"},
            )
        )
        assert answered["answer"]["via"] == "agent"
        assert answered["answer"]["share_link_id"] == scope["link"]["id"]

        outside = await _call(
            session,
            "answer_question",
            {"question_id": str(scope["outside"].id), "text": "Нельзя"},
        )
        assert outside.is_error
        assert "не найден" in _error(outside).lower()

        diagram = _payload(await _call(session, "get_diagram", {"project_id": project_id}))
        assert diagram["review_scope"] == [scope["scoped_lane"]]
        diagram_codes = {question["code"] for question in diagram["questions"]}
        assert {"Q-901", "Q-902"} <= diagram_codes
        assert "Q-903" not in diagram_codes

        blocked = await _call(
            session, "add_source", {"project_id": project_id, "text": "Новый материал"}
        )
        assert blocked.is_error
        assert "sources:write" in _error(blocked) or "Ссылка проверки" in _error(blocked)
        saved = await _call(
            session,
            "save_diagram",
            {"project_id": project_id, "xml": str(finished["xml"])},
        )
        assert saved.is_error


# ---------- журнал активности ----------


async def test_agent_activity_shows_agent_sources_and_answers(stack: Stack) -> None:
    owner = await stack.user("activity-owner@example.com")
    finished = await _finished_project(owner)
    project_id = str(finished["project"])
    lane_by_id, element_lane = await _lanes(owner, project_id)
    scoped_lane = next(iter(lane_by_id))
    node = next(
        (element for element, lane in element_lane.items() if lane == scoped_lane), scoped_lane
    )
    question = await _add_question(stack, project_id, code="Q-910", element_ids=[node])
    link = await _review_link(owner, project_id, [scoped_lane])
    review_secret = _secret(str(link["url_path"]))
    stranger = await stack.user("activity-reviewer@example.com")
    review_token = await _agent_token(stranger, review_secret)

    personal = await owner.post(
        "/me/api-tokens",
        json={
            "name": PERSONAL_TOKEN_NAME,
            "scopes": ["projects:read", "sources:write", "questions:answer"],
        },
    )
    assert personal.status_code == 201, personal.text
    async with _mcp_server(stack) as connect:
        agent_session = await connect(personal.json()["secret"])
        added = _payload(
            await _call(
                agent_session,
                "add_source",
                {
                    "project_id": project_id,
                    "text": "Материал из Confluence про согласование.",
                    "title": "Confluence: согласование",
                },
            )
        )
        assert added["source"]["origin"] == "agent"

        review_session = await connect(str(review_token["secret"]))
        _payload(
            await _call(
                review_session,
                "answer_question",
                {"question_id": str(question.id), "text": "Согласует начальник отдела"},
            )
        )

    activity = await owner.get(f"/projects/{project_id}/agent-activity")
    assert activity.status_code == 200, activity.text
    body = activity.json()
    kinds = {item["kind"] for item in body["items"]}
    assert "source_added" in kinds
    assert "answer_added" in kinds
    source_event = next(item for item in body["items"] if item["kind"] == "source_added")
    assert source_event["token_name"] == PERSONAL_TOKEN_NAME
    assert source_event["title"] == "Confluence: согласование"
    answer_event = next(item for item in body["items"] if item["kind"] == "answer_added")
    assert answer_event["token_name"] == str(review_token["name"])
    assert answer_event["share_link_id"] == link["id"]
    assert answer_event["question_code"] == "Q-910"
    assert body["total"] == len(body["items"])

    # Журнал — участникам проекта, не проверяющему и не постороннему.
    reviewer_agent = Agent(stack, str(review_token["secret"]))
    assert (await reviewer_agent.get(f"/projects/{project_id}/agent-activity")).status_code == 403
    stranger_account = await stack.user("activity-stranger@example.com")
    assert (await stranger_account.get(f"/projects/{project_id}/agent-activity")).status_code == 404


async def test_share_role_matrix_viewer_editor_reviewer(stack: Stack) -> None:
    """Матрица ролей ссылки: что открывается, принимается и даёт токен агента."""
    owner = await stack.user("matrix-owner@example.com")
    finished = await _finished_project(owner)
    project_id = str(finished["project"])
    lane_by_id, _ = await _lanes(owner, project_id)
    lane_id = next(iter(lane_by_id))
    viewer = await owner.post(f"/projects/{project_id}/share-links", json={"role": "viewer"})
    editor = await owner.post(f"/projects/{project_id}/share-links", json={"role": "editor"})
    reviewer = await _review_link(owner, project_id, [lane_id])
    viewer_secret = _secret(viewer.json()["url_path"])
    editor_secret = _secret(editor.json()["url_path"])
    reviewer_secret = _secret(str(reviewer["url_path"]))
    guest = await stack.guest()

    # Открытие проекта: viewer и reviewer работают без входа, editor — только после входа.
    assert (await guest.get(f"/shares/{viewer_secret}")).status_code == 200
    reviewer_body = (await guest.get(f"/shares/{reviewer_secret}")).json()
    assert reviewer_body["role"] == "reviewer"
    assert reviewer_body["scope"]["whole_project"] is False
    assert (await guest.get(f"/shares/{editor_secret}")).status_code == 401

    # Принятие: viewer и editor добавляют проект в профиль, проверка — нет.
    account = await stack.user("matrix-editor@example.com")
    assert (await account.post(f"/shares/{viewer_secret}/accept")).status_code == 200
    assert (await guest.post(f"/shares/{editor_secret}/accept")).status_code == 401
    assert (await account.post(f"/shares/{editor_secret}/accept")).status_code == 200
    assert (await account.post(f"/shares/{reviewer_secret}/accept")).status_code == 403

    # Токен агента выдаёт только ссылка проверки.
    issued = await account.post(f"/shares/{reviewer_secret}/agent-token")
    assert issued.status_code == 201, issued.text
    assert (await account.post(f"/shares/{viewer_secret}/agent-token")).status_code == 403
    assert (await account.post(f"/shares/{editor_secret}/agent-token")).status_code == 403


async def test_guest_answers_by_review_link_with_provenance(stack: Stack) -> None:
    """Гость с reviewer-ссылкой отвечает на вопросы области — без аккаунта и токена."""
    owner = await stack.user("guest-answer-owner@example.com")
    finished = await _finished_project(owner)
    scope = await _scope_fixture(stack, owner, finished)
    project_id = scope["project_id"]
    secret = scope["secret"]
    guest = await stack.guest()

    answered = await guest.post(
        f"/shares/{secret}/questions/{scope['inside'].id}/answer",
        json={"text": "Согласует начальник отдела"},
    )
    assert answered.status_code == 200, answered.text
    body = answered.json()
    assert body["status"] == "answered"
    answer = body["answer"]
    assert answer["via"] == "review"
    assert answer["share_link_id"] == scope["link"]["id"]
    short = str(scope["link"]["id"]).replace("-", "")[:8]
    assert short in answer["via_name"]
    assert "Проверка" in answer["via_name"]

    outside = await guest.post(
        f"/shares/{secret}/questions/{scope['outside'].id}/answer",
        json={"text": "Не моя дорожка"},
    )
    assert outside.status_code == 404

    viewer_link = await owner.post(f"/projects/{project_id}/share-links", json={"role": "viewer"})
    viewer_answer = await guest.post(
        f"/shares/{_secret(viewer_link.json()['url_path'])}/questions/"
        f"{scope['inside_second'].id}/answer",
        json={"text": "Просмотр не отвечает"},
    )
    assert viewer_answer.status_code == 403

    # Ответ по ссылке виден в журнале активности как ответ проверяющего.
    activity = await owner.get(f"/projects/{project_id}/agent-activity")
    events = [item for item in activity.json()["items"] if item["kind"] == "answer_added"]
    event = next(item for item in events if item["share_link_id"] == scope["link"]["id"])
    assert event["token_name"] == answer["via_name"]

    # Отозванная ссылка больше не принимает ответы (404, без раскрытия).
    await owner.delete(f"/projects/{project_id}/share-links/{scope['link']['id']}")
    after_revoke = await guest.post(
        f"/shares/{secret}/questions/{scope['inside_second'].id}/answer",
        json={"text": "Поздно"},
    )
    assert after_revoke.status_code == 404


async def test_reviewer_cannot_see_runs_or_events(stack: Stack) -> None:
    """SSE и карточка прогона содержат вопросы всего проекта — проверяющему их не видно."""
    owner = await stack.user("review-runs-owner@example.com")
    finished = await _finished_project(owner)
    scope = await _scope_fixture(stack, owner, finished)
    run_id = finished["run"]
    stranger = await stack.user("review-runs-stranger@example.com")
    issued = await _agent_token(stranger, str(scope["secret"]))
    agent = Agent(stack, str(issued["secret"]))

    assert (await agent.get(f"/runs/{run_id}")).status_code == 403
    assert (await agent.get(f"/runs/{run_id}/events")).status_code == 403

    async with _mcp_server(stack) as connect:
        session = await connect(str(issued["secret"]))
        result = await _call(session, "get_run", {"run_id": str(run_id)})
        assert result.is_error
        assert "прогон" in _error(result).lower()


async def test_mcp_diagram_shows_evidence_for_whole_project_and_common_questions(
    stack: Stack,
) -> None:
    owner = await stack.user("review-diagram-owner@example.com")
    finished = await _finished_project(owner)
    scope = await _scope_fixture(stack, owner, finished)
    project_id = scope["project_id"]
    # Общий вопрос без привязки к схеме: при области он должен оставаться видимым.
    common = await _add_question(stack, project_id, code="Q-950", element_ids=[])
    stranger = await stack.user("review-diagram-stranger@example.com")

    scoped_token = await _agent_token(stranger, str(scope["secret"]))
    async with _mcp_server(stack) as connect:
        session = await connect(str(scoped_token["secret"]))
        diagram = _payload(await _call(session, "get_diagram", {"project_id": project_id}))
        codes = {question["code"] for question in diagram["questions"]}
        assert "Q-950" in codes  # общий вопрос области не выбрасывается
        assert "Q-903" not in codes
        assert diagram["evidence"]

    # Ссылка проверки на весь проект: основания и вопросы должны быть непустыми.
    whole = await _review_link(owner, project_id, [])
    whole_secret = _secret(str(whole["url_path"]))
    whole_token = await _agent_token(stranger, whole_secret)
    async with _mcp_server(stack) as connect:
        session = await connect(str(whole_token["secret"]))
        diagram = _payload(await _call(session, "get_diagram", {"project_id": project_id}))
        assert diagram["review_scope"] == []
        assert diagram["evidence"]
        codes = {question["code"] for question in diagram["questions"]}
        assert {"Q-950", "Q-903"} <= codes  # весь проект: и общий, и «чужая» дорожка
        assert common.code in codes


async def test_review_ignore_denied_and_review_labels_distinguish_links(stack: Stack) -> None:
    owner = await stack.user("review-label-owner@example.com")
    finished = await _finished_project(owner)
    scope = await _scope_fixture(stack, owner, finished)
    project_id = scope["project_id"]
    stranger = await stack.user("review-label-stranger@example.com")

    second_link = await _review_link(owner, project_id, [scope["scoped_lane"]])
    first_token = await _agent_token(stranger, str(scope["secret"]))
    second_token = await _agent_token(stranger, _secret(str(second_link["url_path"])))
    # Названия проверок различаются коротким id ссылки — коллеги больше не сливаются.
    assert first_token["name"] != second_token["name"]
    first_short = str(scope["link"]["id"]).replace("-", "")[:8]
    second_short = str(second_link["id"]).replace("-", "")[:8]
    assert first_short in str(first_token["name"])
    assert second_short in str(second_token["name"])

    # «Не применимо» (ignore) — решение владельца процесса: проверяющему недоступно.
    agent = Agent(stack, str(first_token["secret"]))
    ignored = await agent.post(f"/questions/{scope['inside_second'].id}/ignore")
    assert ignored.status_code == 403


async def test_review_cards_count_only_scoped_questions(stack: Stack) -> None:
    owner = await stack.user("review-counters-owner@example.com")
    finished = await _finished_project(owner)
    scope = await _scope_fixture(stack, owner, finished)
    project_id = scope["project_id"]
    stranger = await stack.user("review-counters-stranger@example.com")
    issued = await _agent_token(stranger, str(scope["secret"]))
    agent = Agent(stack, str(issued["secret"]))

    full_card = next(
        item for item in (await owner.get("/projects")).json()["items"] if item["id"] == project_id
    )
    scoped_card = next(
        item for item in (await agent.get("/projects")).json()["items"] if item["id"] == project_id
    )
    # Карточка проверки считает ровно вопросы области (Q-903 — чужая дорожка, его нет).
    scoped_questions = (
        await (await stack.guest()).get(f"/shares/{scope['secret']}/questions")
    ).json()
    expected_open = sum(1 for q in scoped_questions if q["status"] == "open")
    expected_resolved = sum(1 for q in scoped_questions if q["status"] == "resolved")
    assert scoped_card["counts"]["questions_open"] == expected_open
    assert scoped_card["counts"]["questions_resolved"] == expected_resolved
    assert scoped_card["counts"]["questions_open"] < full_card["counts"]["questions_open"]
    assert scoped_card["access"] == "reviewer"

    async with _mcp_server(stack) as connect:
        session = await connect(str(issued["secret"]))
        listed = _payload(await _call(session, "list_projects"))
        mcp_card = next(item for item in listed["items"] if item["id"] == project_id)
        assert mcp_card["counts"]["questions_open"] == scoped_card["counts"]["questions_open"]
