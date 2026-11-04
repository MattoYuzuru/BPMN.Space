"""Длинные документы (ADR-0012): структурные парсеры, лимиты, предупреждения о неполном чтении."""

import asyncio
import io
import zipfile
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.container import Container
from app.ingest import parsers
from app.ingest.parsers import DocumentParseError, LocalDocumentParser, ParsedDocument
from tests.conftest import API, create_project
from tests.test_services import _make_pdf

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def _p(text: str, *, style: str | None = None, num: tuple[int, int] | None = None) -> str:
    props = ""
    if style:
        props += f'<w:pStyle w:val="{style}"/>'
    if num:
        props += f'<w:numPr><w:ilvl w:val="{num[1]}"/><w:numId w:val="{num[0]}"/></w:numPr>'
    ppr = f"<w:pPr>{props}</w:pPr>" if props else ""
    return f"<w:p>{ppr}<w:r><w:t>{text}</w:t></w:r></w:p>"


def _tc(text: str, span: int = 1, merge: str | None = None) -> str:
    props = f'<w:gridSpan w:val="{span}"/>' if span > 1 else ""
    if merge:
        props += f'<w:vMerge w:val="{merge}"/>' if merge == "restart" else "<w:vMerge/>"
    return f"<w:tc><w:tcPr>{props}</w:tcPr>{_p(text) if text else '<w:p/>'}</w:tc>"


def _docx(body: str) -> bytes:
    styles = (
        f'<w:styles xmlns:w="{W}">'
        '<w:style w:styleId="Heading1"><w:name w:val="heading 1"/></w:style>'
        '<w:style w:styleId="H2"><w:name w:val="Заголовок 2"/></w:style>'
        '<w:style w:styleId="Outline3"><w:name w:val="Custom"/>'
        '<w:pPr><w:outlineLvl w:val="2"/></w:pPr></w:style></w:styles>'
    )
    numbering = (
        f'<w:numbering xmlns:w="{W}">'
        '<w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:numFmt w:val="bullet"/></w:lvl>'
        "</w:abstractNum>"
        '<w:abstractNum w:abstractNumId="1"><w:lvl w:ilvl="0"><w:numFmt w:val="decimal"/></w:lvl>'
        '<w:lvl w:ilvl="1"><w:numFmt w:val="decimal"/></w:lvl></w:abstractNum>'
        '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>'
        '<w:num w:numId="2"><w:abstractNumId w:val="1"/></w:num></w:numbering>'
    )
    document = f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'
    return _zip(
        {"word/document.xml": document, "word/styles.xml": styles, "word/numbering.xml": numbering}
    )


async def test_docx_keeps_headings_lists_and_tables() -> None:
    table = (
        "<w:tbl>"
        f"<w:tr>{_tc('Этап')}{_tc('Срок')}{_tc('Ответственный')}</w:tr>"
        f"<w:tr>{_tc('Проверка')}{_tc('3 дня', merge='restart')}{_tc('Группа | приёма')}</w:tr>"
        f"<w:tr>{_tc('Акт', span=2)}{_tc('Диспетчер')}</w:tr>"
        "</w:tbl>"
    )
    body = (
        _p("Регламент", style="Heading1")
        + _p("Общие положения", style="H2")
        + _p("Уровень три", style="Outline3")
        + _p("Обычный абзац.")
        + _p("Первый пункт", num=(1, 0))
        + _p("Первый шаг", num=(2, 0))
        + _p("Подшаг", num=(2, 1))
        + _p("Второй шаг", num=(2, 0))
        + _p("Третий шаг", num=(2, 0))
        + table
        + _p("После таблицы")
    )
    text = (await LocalDocumentParser().parse_document(file_name="a.docx", data=_docx(body))).text
    lines = text.splitlines()
    assert lines[0] == "# Регламент"
    assert "## Общие положения" in lines
    assert "### Уровень три" in lines
    assert "- Первый пункт" in lines
    assert "1. Первый шаг" in lines
    assert "  1. Подшаг" in lines
    assert "2. Второй шаг" in lines
    assert "3. Третий шаг" in lines
    assert "| Этап | Срок | Ответственный |" in lines
    assert "| --- | --- | --- |" in lines
    assert "| Проверка | 3 дня | Группа \\| приёма |" in lines
    assert "| Акт |  | Диспетчер |" in lines
    assert lines[-1] == "После таблицы"
    assert "" in lines  # таблица отделена пустыми строками


async def test_docx_zip_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    parser = LocalDocumentParser()
    with pytest.raises(DocumentParseError, match="повреждён"):
        await parser.parse(file_name="a.docx", data=b"nope")
    big = _docx(_p("x" * 5000))
    monkeypatch.setattr(parsers, "_MAX_XML_PART_BYTES", 1000)
    with pytest.raises(DocumentParseError, match="слишком большой"):
        await parser.parse(file_name="a.docx", data=big)
    monkeypatch.setattr(parsers, "_MAX_XML_PART_BYTES", 10**9)
    monkeypatch.setattr(parsers, "_MAX_ARCHIVE_MEMBERS", 2)
    with pytest.raises(DocumentParseError, match="слишком большой"):
        await parser.parse(file_name="a.docx", data=big)


async def test_docx_entity_expansion_is_rejected() -> None:
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE d [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]>'
        f'<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>&b;</w:t></w:r></w:p></w:body>'
        "</w:document>"
    )
    with pytest.raises(DocumentParseError, match="повреждён"):
        await LocalDocumentParser().parse(
            file_name="a.docx", data=_zip({"word/document.xml": bomb})
        )


def _xlsx(sheets: dict[str, list[list[object]]]) -> bytes:
    workbook = Workbook()
    workbook.remove(workbook["Sheet"])
    for name, rows in sheets.items():
        sheet = workbook.create_sheet(name)
        for row in rows:
            sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


async def test_xlsx_sheets_become_markdown_tables() -> None:
    data = _xlsx(
        {
            "Заявки": [["Номер", "Статус", "Срок"], [1, "Принята", 3.0], [2, "Отказ", None]],
            "Пустой": [[None, None]],
            "Роли": [["Роль"], ["Диспетчер"], [], ["Монтёр"]],
        }
    )
    text = await LocalDocumentParser().parse(file_name="t.xlsx", data=data)
    assert "## Лист «Заявки»" in text
    assert "| Номер | Статус | Срок |" in text
    assert "| 1 | Принята | 3 |" in text
    assert "| 2 | Отказ |  |" in text
    assert "Пустой" not in text
    assert text.index("| Диспетчер |") < text.index("| Монтёр |")


async def test_xlsx_row_cap_is_reported_not_silent() -> None:
    rows: list[list[object]] = [["n"], *([i] for i in range(10))]
    parsed = await LocalDocumentParser(max_sheet_rows=4).parse_document(
        file_name="t.xlsx", data=_xlsx({"Данные": rows})
    )
    assert parsed.text.count("\n| ") >= 3
    assert parsed.warning is not None
    assert "прочитаны первые 4 строк" in parsed.warning
    assert "ещё 7 строк" in parsed.warning


async def test_broken_xlsx() -> None:
    with pytest.raises(DocumentParseError, match="повреждён"):
        await LocalDocumentParser().parse(file_name="t.xlsx", data=b"nope")


def _pptx() -> bytes:
    a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    p = "http://schemas.openxmlformats.org/presentationml/2006/main"

    def slide(title: str, body: str, table: str = "") -> str:
        return (
            f'<p:sld xmlns:p="{p}" xmlns:a="{a}"><p:cSld><p:spTree>'
            f'<p:sp><p:nvSpPr><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>'
            f"<p:txBody><a:p><a:r><a:t>{title}</a:t></a:r></a:p></p:txBody></p:sp>"
            f'<p:sp><p:nvSpPr><p:nvPr><p:ph type="body"/></p:nvPr></p:nvSpPr>'
            f"<p:txBody><a:p><a:r><a:t>{body}</a:t></a:r></a:p></p:txBody></p:sp>"
            f'<p:sp><p:nvSpPr><p:nvPr><p:ph type="sldNum"/></p:nvPr></p:nvSpPr>'
            f"<p:txBody><a:p><a:r><a:t>7</a:t></a:r></a:p></p:txBody></p:sp>{table}"
            "</p:spTree></p:cSld></p:sld>"
        )

    table = (
        "<a:tbl><a:tr><a:tc><a:txBody><a:p><a:r><a:t>Роль</a:t></a:r></a:p></a:txBody></a:tc>"
        "<a:tc><a:txBody><a:p><a:r><a:t>Срок</a:t></a:r></a:p></a:txBody></a:tc></a:tr>"
        "<a:tr><a:tc><a:txBody><a:p><a:r><a:t>Диспетчер</a:t></a:r></a:p></a:txBody></a:tc>"
        "<a:tc><a:txBody><a:p><a:r><a:t>2 дня</a:t></a:r></a:p></a:txBody></a:tc></a:tr></a:tbl>"
    )
    notes = (
        f'<p:notes xmlns:p="{p}" xmlns:a="{a}"><p:cSld><p:spTree><p:sp><p:txBody>'
        "<a:p><a:r><a:t>Говорить медленно</a:t></a:r></a:p></p:txBody></p:sp></p:spTree>"
        "</p:cSld></p:notes>"
    )
    return _zip(
        {
            "ppt/slides/slide10.xml": slide("Итоги", "Выводы"),
            "ppt/slides/slide2.xml": slide("Процесс", "Заявку принимает оператор", table),
            "ppt/notesSlides/notesSlide2.xml": notes,
        }
    )


async def test_pptx_slides_in_numeric_order_with_tables_and_notes() -> None:
    text = await LocalDocumentParser().parse(file_name="d.pptx", data=_pptx())
    assert text.index("## Слайд 1: Процесс") < text.index("## Слайд 2: Итоги")
    assert "- Заявку принимает оператор" in text
    assert "| Диспетчер | 2 дня |" in text
    assert "Заметки докладчика: Говорить медленно" in text
    assert "- 7" not in text
    with pytest.raises(DocumentParseError, match="нет слайдов"):
        await LocalDocumentParser().parse(file_name="d.pptx", data=_zip({"x": "y"}))


async def test_pdf_with_scans_stays_ready_with_pages_and_warning() -> None:
    pdf = _make_pdf(["First page", "", "Third", ""])
    parsed = await LocalDocumentParser().parse_document(file_name="a.pdf", data=pdf)
    assert parsed.unreadable_pages == (2, 4)
    assert parsed.warning is not None
    assert "страницах: 2, 4" in parsed.warning
    assert "[Страница 3]\nThird" in parsed.text


async def test_large_csv_is_not_capped_at_forty_thousand() -> None:
    rows = ("a,b\n" + "".join(f"{i},значение значение\n" for i in range(5_000))).encode()
    text = await LocalDocumentParser(max_text_chars=1_500_000).parse(file_name="a.csv", data=rows)
    assert len(text) > 100_000
    assert "Строка 5001:" in text
    with pytest.raises(DocumentParseError, match="превышает лимит"):
        await LocalDocumentParser(max_text_chars=50_000).parse(file_name="a.csv", data=rows)


def test_parsed_document_warning_joins_parts() -> None:
    assert ParsedDocument(text="x").warning is None
    assert ParsedDocument(text="x", warnings=("a.", "b.")).warning == "a. b."


def test_mixed_pdf_upload_is_ready_with_warning_and_context_notes_it(client: TestClient) -> None:
    from app.domain.models import SourceStatus  # noqa: PLC0415
    from app.ingest.context import build_run_context  # noqa: PLC0415

    project_id = create_project(client)
    response = client.post(
        f"{API}/projects/{project_id}/sources/file",
        files={"file": ("regl.pdf", _make_pdf(["Page one", "", "Page three"]), "application/pdf")},
    )
    assert response.status_code == 201
    project = client.get(f"{API}/projects/{project_id}").json()
    source = next(s for s in project["sources"] if s["file_name"] == "regl.pdf")
    assert source["status"] == "ready"
    assert source["unreadable_pages"] == [2]
    assert "страницах: 2" in source["warning"]
    assert "Page three" in source["content"]

    container: Container = client.app.state.container  # type: ignore[attr-defined]
    stored = asyncio.run(container.repos.sources.list_by_project(UUID(project_id)))
    assert all(s.status is SourceStatus.READY for s in stored)
    detail = asyncio.run(container.repos.projects.get(UUID(project_id)))
    assert detail is not None
    context = build_run_context(
        project=detail, sources=stored, questions=[], versions=[], budget_chars=120_000
    )
    assert any("прочитан не полностью" in w and "regl.pdf" in w for w in context.warnings)
    assert context.analysis_input_complete is False
