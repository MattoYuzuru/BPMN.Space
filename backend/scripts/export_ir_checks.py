"""Записанные ответы адаптера → IR/XML → настоящий HTTP layout/lint, без live LLM."""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.analysis import AnalysisResult, ContextSource, RunContext
from app.domain.bpmn.xsd import require_valid_bpmn
from app.domain.models import SourceKind
from app.infra.bpmn_tools import HttpBpmnTools
from app.llm.openai_compatible import OpenAICompatiblePipeline

FIXTURES = Path(__file__).resolve().parents[1] / "app" / "fixtures" / "ir"


async def export(url: str, output: Path) -> None:
    fixtures = FIXTURES
    source = ContextSource(
        id=UUID("11111111-1111-4111-8111-111111111111"),
        title="Регламент согласования",
        kind=SourceKind.TEXT,
        content=await asyncio.to_thread((fixtures / "source.txt").read_text),
        created_at=datetime.now(UTC),
    )
    tools = HttpBpmnTools(url)
    await asyncio.to_thread(output.mkdir, parents=True, exist_ok=True)
    for path in sorted(fixtures.glob("*.json")):
        recorded = await asyncio.to_thread(path.read_text)
        pipeline = OpenAICompatiblePipeline(
            api_key="recorded-never-sent", complete=lambda _s, _p, value=recorded: value
        )
        draft = await pipeline.structure(
            RunContext(
                project_id=uuid4(),
                project_title="Согласование заявки",
                sources=[source],
                questions=[],
            ),
            AnalysisResult(),
        )
        xml = await tools.layout(draft.xml)
        require_valid_bpmn(xml)
        errors = [issue for issue in await tools.lint(xml) if issue.severity.value == "error"]
        if errors:
            raise ValueError(errors)
        await asyncio.to_thread((output / f"{path.stem}.bpmn").write_text, xml)
        await asyncio.to_thread(
            (output / f"{path.stem}.ir.json").write_text,
            json.dumps(draft.ir, ensure_ascii=False, indent=2),
        )
        print(f"{path.stem}: IR/HTTP layout/XSD/full lint ok → {output / (path.stem + '.bpmn')}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tools-url", default="http://127.0.0.1:3000")
    parser.add_argument("--output", type=Path, default=Path("../reports/tmp/generated-ir"))
    args = parser.parse_args()
    asyncio.run(export(args.tools_url, args.output))
