"""Покрытие всех частей и отказ вместо незаметной потери оснований."""

import json
from dataclasses import replace

import pytest

from app.ingest.parsers import DocumentParseError, LocalDocumentParser
from app.llm.base import PipelineError
from app.llm.evidence_context import prepare_evidence_context
from tests.test_graph_repair_feedback import _context
from tests.test_services import _make_pdf


async def test_short_sources_are_not_capped_at_forty_thousand():
    context = _context("а" * 50_000)

    async def unused(_system, _prompt):
        raise AssertionError("Короткий контекст не требует вызова модели")

    result = await prepare_evidence_context(context, unused)
    assert len(result.sources[0].content) == 50_000


async def test_tail_and_each_chunk_are_read():
    context = replace(
        _context("начало " + "а" * 4_000 + " важный конец"), analysis_budget_chars=2_000
    )
    seen = []

    async def complete(_system, prompt):
        chunk = json.loads(prompt)["text"]
        seen.append(chunk)
        return json.dumps({"quotes": ["важный конец"] if "важный конец" in chunk else []})

    result = await prepare_evidence_context(context, complete)
    assert len(seen) > 1
    assert "важный конец" in result.sources[0].content
    assert sum(len(x) - 200 for x in seen) >= 3_000


async def test_invented_quote_is_rejected():
    async def complete(_system, _prompt):
        return '{"quotes": ["выдумка"]}'

    with pytest.raises(PipelineError, match="основания"):
        await prepare_evidence_context(
            replace(_context("а" * 4_000), analysis_budget_chars=2_000), complete
        )


async def test_mixed_pdf_cannot_silently_skip_scanned_page():
    with pytest.raises(DocumentParseError, match="страницах 2"):
        await LocalDocumentParser().parse(
            file_name="mixed.pdf", data=_make_pdf(["Valid process", ""])
        )
