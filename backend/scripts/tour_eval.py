"""Проверка материалов тура на модели: сколько открытых вопросов и строится ли схема.

Тур строится на `.docx` «Записка со встречи» и тексте-подсказке; модель должна стабильно
задавать вопросы (критерий: ≥ 2 открытых вопроса минимум в 4 прогонах из 5 и схема во всех).

    # mock (бесплатно): ровно 2 вопроса и схема
    uv run python scripts/tour_eval.py

    # настоящая модель (тратит ключ DeepSeek; ключ — в .env в корне репозитория)
    LLM_PROVIDER=deepseek DEEPSEEK_API_KEY=... MOCK_DELAY_SCALE=0 \
        uv run python scripts/tour_eval.py --runs 5

Работает на in-memory хранилище без аккаунтов и ничего не пишет на диск.
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings
from app.container import build_container
from app.domain.models import QuestionStatus, RunMode, RunStatus, SourceKind
from app.fixtures.samples import TOUR_SAMPLE_ID, tour_text_suggestion

MIN_QUESTIONS = 2


async def one_run(index: int) -> tuple[bool, int, float]:
    settings = Settings(auth_enabled=False, seed_demo_data=False, database_url=None)
    container = build_container(settings)
    project = (
        await container.projects.create(title="Мой первый процесс", description=None)
    ).project
    source, _ = await container.samples.add(project.id, TOUR_SAMPLE_ID)
    await container.sources.process_file(source.id)
    await container.sources.create_text(
        project.id,
        content=tour_text_suggestion(),
        title=None,
        kind=SourceKind.TEXT,
        duration_sec=None,
    )
    started = time.perf_counter()
    run = await container.runs.start(project.id, mode=RunMode.BUILD, created_by=None)
    await container.spawner.wait_idle()
    run = await container.runs.get(run.id)
    seconds = time.perf_counter() - started
    questions = await container.questions.list(project.id, status=QuestionStatus.OPEN)
    versions = await container.versions.list(project.id)
    built = run.status is RunStatus.SUCCEEDED and bool(versions)
    print(
        f"прогон {index}: {run.status.value}, схема={'да' if built else 'нет'}, "
        f"открытых вопросов={len(questions)}, {seconds:.0f} с"
        + (f", ошибка: {run.error}" if run.error else "")
    )
    return built, len(questions), seconds


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args()
    results = [await one_run(i) for i in range(1, args.runs + 1)]
    with_questions = sum(1 for _, count, _ in results if count >= MIN_QUESTIONS)
    with_diagram = sum(1 for built, _, _ in results if built)
    total = (
        f"схема {with_diagram}/{args.runs}, ≥ {MIN_QUESTIONS} вопросов {with_questions}/{args.runs}"
    )
    print(f"итого: {total}")
    needed = max(args.runs - 1, 1)  # 4 из 5
    ok = with_diagram == args.runs and with_questions >= needed
    print("критерий выполнен" if ok else "критерий НЕ выполнен")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
