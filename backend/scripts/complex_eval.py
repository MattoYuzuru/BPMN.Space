"""Три сложных регламента: изолированный прогон с сохранением реальных результатов.

По умолчанию используются записанные правила mock. --live разрешает настроенный
LLM-провайдер; согласуйте объём и бюджет до запуска. PostgreSQL и аккаунты не изменяются.
Нужен запущенный Node bpmn-tools: --tools-url http://127.0.0.1:3000.
"""

# ruff: noqa: E402 — app импортируется после подключения backend к пути отдельного скрипта.

import argparse
import asyncio
import json
import re
import sys
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.container import build_container
from app.domain.bpmn.importer import import_graph
from app.domain.models import RunMode, RunStatus, SourceKind
from app.fixtures import FIXTURES_DIR, read_text
from app.fixtures.complex_examples import COMPLEX_EXAMPLES, ComplexExample


def _normal(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip(" .?!")


def _tasks(graph: dict) -> Counter:
    roles = {lane["id"]: _normal(lane["name"]) for lane in graph["lanes"]}
    return Counter(
        (_normal(node["name"]), roles[node["lane"]])
        for node in graph["nodes"]
        if node["type"] == "task"
    )


async def one_case(example: ComplexExample, settings: Settings, output: Path) -> bool:
    container = build_container(settings)
    project = (await container.projects.create(title=example.title, description=None)).project
    await container.sources.create_text(
        project.id,
        content=read_text(f"{example.fixture}.md"),
        title=example.title,
        kind=SourceKind.TEXT,
        duration_sec=None,
    )
    started = time.monotonic()
    run = await container.runs.start(project.id, mode=RunMode.BUILD, created_by=None)
    await container.spawner.wait_idle()
    run = await container.runs.get(run.id)
    versions = await container.versions.list(project.id)
    questions = await container.questions.list(project.id, status=None)
    result = {
        "case": example.key,
        "provider": settings.llm_provider,
        "model": run.model,
        "output_budget": settings.llm_json_max_tokens,
        "seconds": round(time.monotonic() - started, 1),
        "status": run.status.value,
        "error": run.error,
        "warnings": run.warnings,
        "questions": [asdict(question) for question in questions],
        "run": asdict(run),
    }
    if versions:
        version = await container.versions.get(versions[0].id)
        graph = import_graph(version.xml).model_dump(mode="json")
        expected = json.loads((FIXTURES_DIR / "ir" / f"{example.fixture}.json").read_text())
        result.update(
            graph=graph,
            report=asdict(version.report),
            trace={key: asdict(quote) for key, quote in version.trace.items()},
            nodes=len(graph["nodes"]),
            flows=len(graph["flows"]),
            tasks_missing=list((_tasks(expected) - _tasks(graph)).elements()),
            tasks_extra=list((_tasks(graph) - _tasks(expected)).elements()),
        )
        (output / f"{example.fixture}.bpmn").write_text(version.xml)
    (output / f"{example.fixture}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str)
    )
    print(
        f"{example.key}: {run.status.value}; вопросов {len(questions)}; "
        f"{result['seconds']} с" + (f"; {run.error}" if run.error else ""),
        flush=True,
    )
    return run.status is RunStatus.SUCCEEDED and bool(versions)


async def main() -> int:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "Проверка сложных схем").splitlines()[0]
    )
    parser.add_argument("--live", action="store_true", help="Вызвать настроенный платный провайдер")
    parser.add_argument("--tools-url", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "complex-eval")
    parser.add_argument("--cases", nargs="+", choices=[item.key for item in COMPLEX_EXAMPLES])
    args = parser.parse_args()
    load_dotenv(ROOT / ".env", override=False)
    settings = Settings(
        auth_enabled=False,
        seed_demo_data=False,
        database_url=None,
        bpmn_tools_url=args.tools_url,
        mock_delay_scale=0,
        stt_provider="mock",
    )
    if not args.live:
        settings = settings.model_copy(update={"llm_provider": "mock"})
    if args.live and settings.llm_provider == "mock":
        parser.error("Для --live настройте LLM_PROVIDER и ключ в защищённом окружении")
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    for example in COMPLEX_EXAMPLES:
        if args.cases is None or example.key in args.cases:
            results.append(await one_case(example, settings, args.output))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
