"""Cookie `Secure`, заголовки скачивания XML и проверка пользовательского XML."""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.container import build_container
from app.domain.bpmn.document import BpmnFormatError, ensure_safe_xml
from app.fixtures import read_bpmn
from app.main import create_app
from app.services.auth import build_fastapi_users
from tests.conftest import API, DEMO

BPMN = 'xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"'


def _csrf_cookie(**settings: object) -> str:
    config = Settings(database_url=None, seed_demo_data=False, auth_enabled=True, **settings)  # type: ignore[arg-type]
    with TestClient(create_app(config, container=build_container(config))) as client:
        response = client.get(f"{API}/auth/csrf")
        return response.headers["set-cookie"]


@pytest.mark.parametrize(
    ("env", "secure_setting", "expected"),
    [
        ("production", None, True),
        ("prod", None, True),
        ("dev", None, False),
        ("docker", None, False),
        ("production", False, False),
        ("dev", True, True),
    ],
)
def test_cookie_secure_follows_env_unless_overridden(
    env: str, secure_setting: bool | None, expected: bool
) -> None:
    settings = Settings(app_env=env, session_cookie_secure=secure_setting)
    assert settings.cookie_secure is expected
    assert ("Secure" in _csrf_cookie(app_env=env, session_cookie_secure=secure_setting)) is expected


@pytest.mark.parametrize("secure", [True, False])
def test_session_cookie_uses_the_same_secure_flag(secure: bool) -> None:
    _, backend = build_fastapi_users(cookie_secure=secure)
    assert backend.transport.cookie_secure is secure


def test_xml_download_headers_without_auth(client: TestClient) -> None:
    version = client.get(f"{API}/projects/{DEMO}").json()["latest_version"]
    response = client.get(f"{API}/versions/{version['id']}/xml")

    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith('attachment; filename="diagram-v')
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == "default-src 'none'; sandbox"


def test_safe_xml_accepts_generated_and_bpmn_js_documents() -> None:
    ensure_safe_xml(read_bpmn("tp861_v1"))
    colored = (
        f'<bpmn:definitions {BPMN} xmlns:bioc="http://bpmn.io/schema/bpmn/biocolor/1.0" '
        'xmlns:color="http://www.omg.org/spec/BPMN/non-normative/color/1.0" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        '<bpmn:process id="p"><bpmn:task id="t" bioc:fill="#fff" color:stroke="#000" '
        'xsi:type="bpmn:tTask"/></bpmn:process></bpmn:definitions>'
    )
    ensure_safe_xml(colored)


def test_bpmn_script_of_script_task_is_allowed() -> None:
    ensure_safe_xml(
        f"<bpmn:definitions {BPMN}><bpmn:process id='p'><bpmn:scriptTask id='t'>"
        "<bpmn:script>1</bpmn:script></bpmn:scriptTask></bpmn:process></bpmn:definitions>"
    )


@pytest.mark.parametrize(
    ("xml", "fragment"),
    [
        (
            f'<?xml version="1.0"?><?xml-stylesheet href="x.xsl"?><bpmn:definitions {BPMN}/>',
            "инструкции",
        ),
        (f"<bpmn:definitions {BPMN}><?php x ?></bpmn:definitions>", "инструкции"),
        (f'<!DOCTYPE d [<!ENTITY e "x">]><bpmn:definitions {BPMN}>&e;</bpmn:definitions>', "DTD"),
        (
            f'<!DOCTYPE d [<!ENTITY e SYSTEM "http://evil.example/x">]>'
            f"<bpmn:definitions {BPMN}>&e;</bpmn:definitions>",
            "DTD",
        ),
        (
            f'<bpmn:definitions {BPMN}><s:SCRIPT xmlns:s="http://www.w3.org/1999/xhtml"/>'
            "</bpmn:definitions>",
            "вне пространств",
        ),
        (
            f'<bpmn:definitions {BPMN}><svg xmlns="http://www.w3.org/2000/svg"/></bpmn:definitions>',
            "вне пространств",
        ),
        (
            f"<bpmn:definitions {BPMN}><plain/></bpmn:definitions>".replace(
                "<plain/>", "<x xmlns=''/>"
            ),
            "вне пространств",
        ),
        (f'<bpmn:definitions {BPMN} xmlns:x="urn:x" x:a="1"/>', "Атрибут"),
        ("<bpmn:definitions", "повреждён"),
    ],
)
def test_safe_xml_rejects_dangerous_documents(xml: str, fragment: str) -> None:
    with pytest.raises(BpmnFormatError, match=fragment):
        ensure_safe_xml(xml)


def test_manual_save_returns_422_for_dangerous_xml(client: TestClient) -> None:
    xml = (
        f'<bpmn:definitions {BPMN}><bpmn:process id="p"/><x:b xmlns:x="urn:x"/></bpmn:definitions>'
    )
    response = client.put(f"{API}/projects/{DEMO}/diagram", json={"xml": xml})

    assert response.status_code == 422
    assert "вне пространств имён BPMN 2.0" in response.json()["detail"]
