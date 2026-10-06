"""Официальная XSD — runtime-гейт версий, а не только проверка учебных фикстур."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.container import Container
from app.domain.analysis import AnalysisResult, DiagramDraft, RunContext
from app.domain.bpmn.document import BpmnFormatError
from app.domain.bpmn.xsd import require_valid_bpmn, xsd_errors
from app.domain.models import Report, Version, VersionDiff, VersionOrigin
from app.fixtures import read_bpmn
from tests.conftest import API, DEMO, read_events

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
INVALID = (
    f'<bpmn:definitions xmlns:bpmn="{BPMN_NS}" targetNamespace="urn:test">\n'
    '<bpmn:process id="Process"><bpmn:banana id="Bad_1"/></bpmn:process>'
    "</bpmn:definitions>"
)


@pytest.mark.parametrize(
    "xml",
    [
        INVALID,
        INVALID.replace("banana", "task").replace('id="Bad_1"', 'id="Bad_1" invented="yes"'),
        INVALID.replace("banana", "task").replace(' targetNamespace="urn:test"', ""),
        INVALID.replace("banana", "process"),
    ],
)
def test_xsd_rejects_invalid_elements_attributes_and_structure(xml: str) -> None:
    errors = xsd_errors(xml)
    assert errors
    assert all("Строка" in error for error in errors)
    with pytest.raises(BpmnFormatError, match="XSD"):
        require_valid_bpmn(xml)


def test_xsd_diagnostic_identifies_the_offending_element() -> None:
    assert "Bad_1" in xsd_errors(INVALID)[0]
    assert "banana" in xsd_errors(INVALID)[0]


def test_xsd_accepts_bpmn_js_colors_and_di() -> None:
    xml = read_bpmn("tp861_v2")
    xml = xml.replace(
        "<bpmn:definitions ",
        '<bpmn:definitions xmlns:bioc="http://bpmn.io/schema/bpmn/biocolor/1.0" ',
        1,
    )
    xml = xml.replace("<bpmndi:BPMNShape ", '<bpmndi:BPMNShape bioc:fill="#ffffff" ', 1)
    assert xsd_errors(xml) == []


@pytest.mark.parametrize(
    "xml",
    [
        "<bpmn:definitions",
        '<!DOCTYPE x [<!ENTITY data SYSTEM "file:///etc/passwd">]>'
        f'<bpmn:definitions xmlns:bpmn="{BPMN_NS}" targetNamespace="urn:test">'
        '<bpmn:process id="Process">&data;</bpmn:process></bpmn:definitions>',
        '<?xml-stylesheet href="https://example.test/style.xsl"?>' + INVALID,
        INVALID.replace("bpmn:banana", "foreign:banana").replace(
            ' targetNamespace="urn:test"',
            ' xmlns:foreign="urn:foreign" targetNamespace="urn:test"',
        ),
        INVALID.replace(
            '<bpmn:process id="Process">',
            '<bpmn:import namespace="urn:foreign" location="https://example.test/types.xsd" '
            'importType="http://www.w3.org/2001/XMLSchema"/><bpmn:process id="Process">',
        ),
    ],
)
def test_unsafe_or_malformed_xml_never_reaches_schema_validation(xml: str) -> None:
    with pytest.raises(BpmnFormatError):
        xsd_errors(xml)


def test_manual_xsd_failure_returns_422_without_head_change(client: TestClient) -> None:
    before = client.get(f"{API}/projects/{DEMO}").json()
    response = client.put(
        f"{API}/projects/{DEMO}/diagram",
        json={"xml": INVALID, "base_version_id": before["latest_version"]["id"]},
    )
    assert response.status_code == 422
    assert "Bad_1" in response.json()["detail"]
    after = client.get(f"{API}/projects/{DEMO}").json()
    assert after["latest_version"]["id"] == before["latest_version"]["id"]
    assert after["counts"]["versions"] == before["counts"]["versions"]


class _InvalidDraft:
    model_name = "recorded-invalid"

    async def analyze(self, context: RunContext) -> AnalysisResult:
        return AnalysisResult()

    async def structure(self, context: RunContext, analysis: AnalysisResult) -> DiagramDraft:
        return DiagramDraft(xml=INVALID)


def test_generated_xsd_failure_preserves_previous_working_version(
    client: TestClient, container: Container
) -> None:
    before = client.get(f"{API}/projects/{DEMO}").json()
    container.runs._pipeline = _InvalidDraft()
    run = client.post(f"{API}/projects/{DEMO}/runs", json={"mode": "build"}).json()
    events = read_events(client, run["id"])
    assert not any(kind == "version" for kind, _ in events)
    assert events[-1][1]["run"]["status"] == "failed"
    assert "XSD" in events[-1][1]["run"]["error"]
    after = client.get(f"{API}/projects/{DEMO}").json()
    assert after["latest_version"]["id"] == before["latest_version"]["id"]
    assert after["counts"]["versions"] == before["counts"]["versions"]


async def test_historical_validation_flags_are_rechecked_without_rewriting_storage(
    container: Container,
) -> None:
    project = await container.projects.create(title="Исторический XML", description=None)
    historical = Version(
        id=uuid4(),
        project_id=project.project.id,
        number=1,
        origin=VersionOrigin.MANUAL,
        created_at=datetime.now(UTC),
        xml=INVALID,
        diff=VersionDiff(),
        report=Report(xsd_valid=True),
    )
    await container.repos.versions.add(historical)
    for projected in (
        await container.versions.get(historical.id),
        (await container.versions.list(historical.project_id))[0],
        (await container.projects.detail(historical.project_id)).latest_version,
    ):
        assert projected is not None
        assert projected.report.xsd_valid is False
        assert projected.xml == historical.xml
    stored = await container.repos.versions.get(historical.id)
    assert stored == historical
    valid = replace(
        historical,
        id=uuid4(),
        number=2,
        xml=read_bpmn("tp861_v2"),
        report=Report(xsd_valid=False),
    )
    await container.repos.versions.add(valid)
    assert (await container.versions.get(valid.id)).report.xsd_valid is True
    assert await container.repos.versions.get(valid.id) == valid
