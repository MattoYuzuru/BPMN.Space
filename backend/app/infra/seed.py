"""Детерминированный сид демо-данных для in-memory и PostgreSQL хранилищ.

- Главный проект «Технологическое присоединение к электросетям» (ПП РФ № 861): три источника
  (регламент, голосовая заметка, «Финансы проекта.docx»), шесть вопросов во всех статусах,
  две версии схемы. Следующий анализ решит два вопроса и задаст новый, сборка даст v3.
- 40 проектов для бесконечной прокрутки: 4 с собственными схемами (вывод в ремонт,
  наряд-допуск, закупка по 223-ФЗ, договор энергоснабжения) и 36 типовых.

Всё детерминировано: id — uuid5 от ключа, случайность — `random.Random(SEED)`, даты отсчитываются
от `BASE_TIME`. Поэтому id демо-проекта стабилен между перезапусками (`DEMO_PROJECT_ID`).
PostgreSQL заполняется идемпотентным демо-сидом при старте приложения.
"""

import random
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid5

from app.domain.analysis import ContextSource
from app.domain.bpmn.document import parse_bpmn
from app.domain.bpmn.linear import LinearStep, build_linear_diagram
from app.domain.bpmn.lint import lint_document
from app.domain.models import (
    Answer,
    Project,
    Question,
    QuestionStatus,
    Quote,
    Run,
    RunMode,
    RunStatus,
    Source,
    SourceKind,
    SourceStatus,
    Version,
    VersionOrigin,
)
from app.domain.questions import find_source_with_quote, run_summary
from app.domain.runs import stages_for
from app.domain.versions import build_version
from app.fixtures import playbook as pb
from app.fixtures import read_bpmn, read_text
from app.fixtures.catalog import TOPICS
from app.fixtures.generic import generic_questions, meeting_note, regulation_text
from app.fixtures.types import DiagramRule, QuestionRule, Topic

SEED = 861
NAMESPACE = UUID("6f0c2d4e-8a51-4c1e-9b7a-0d3e5f861000")
BASE_TIME = datetime(2026, 10, 1, 6, 0, tzinfo=UTC)
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def seed_id(key: str) -> UUID:
    return uuid5(NAMESPACE, key)


DEMO_PROJECT_ID = seed_id("project/tp861")


@dataclass(slots=True)
class SeedData:
    projects: list[Project] = field(default_factory=list[Project])
    sources: list[Source] = field(default_factory=list[Source])
    questions: list[Question] = field(default_factory=list[Question])
    runs: list[Run] = field(default_factory=list[Run])
    versions: list[Version] = field(default_factory=list[Version])


class _ProjectBuilder:
    """Строит один проект по шагам хронологии; `at` каждого шага двигает `updated_at`."""

    def __init__(self, data: SeedData, key: str, title: str, description: str, at: datetime):
        self.data = data
        self.key = key
        self.project = Project(
            id=seed_id(f"project/{key}"),
            title=title,
            description=description,
            created_at=at,
            updated_at=at,
        )
        data.projects.append(self.project)
        self.sources: list[Source] = []
        self.questions: list[Question] = []
        self.versions: list[Version] = []

    def _touch(self, at: datetime) -> None:
        self.project.updated_at = max(self.project.updated_at, at)

    def source(
        self, name: str, kind: SourceKind, title: str, content: str, at: datetime, **extra: object
    ) -> Source:
        source = Source(
            id=seed_id(f"{self.key}/source/{name}"),
            project_id=self.project.id,
            kind=kind,
            title=title,
            content=content,
            status=SourceStatus.READY,
            active=True,
            created_at=at,
        )
        for attr, value in extra.items():
            setattr(source, attr, value)
        self.sources.append(source)
        self.data.sources.append(source)
        self._touch(at)
        return source

    def _context(self) -> list[ContextSource]:
        return [
            ContextSource(
                id=s.id, kind=s.kind, title=s.title, content=s.content, created_at=s.created_at
            )
            for s in self.sources
            if s.active and s.status is SourceStatus.READY
        ]

    def quote(self, text: str) -> Quote | None:
        source = find_source_with_quote(text, self._context())
        return Quote(source_id=source.id, quote=text) if source else None

    def run(self, name: str, mode: RunMode, at: datetime) -> Run:
        run = Run(
            id=seed_id(f"{self.key}/run/{name}"),
            project_id=self.project.id,
            mode=mode,
            status=RunStatus.SUCCEEDED,
            started_at=at,
            stage=stages_for(mode)[-1],
            progress=1.0,
            finished_at=at + timedelta(seconds=7 if mode is RunMode.BUILD else 5),
        )
        self.data.runs.append(run)
        self._touch(at)
        return run

    def finish_run(self, run: Run, *, resolved: int = 0) -> None:
        run.summary = run_summary(self.questions, run_id=run.id, resolved_now=resolved)

    def ask(self, rule: QuestionRule, run: Run) -> Question:
        question = Question(
            id=seed_id(f"{self.key}/question/{len(self.questions) + 1}"),
            project_id=self.project.id,
            code=f"Q-{len(self.questions) + 1}",
            kind=rule.kind,
            severity=rule.severity,
            status=QuestionStatus.OPEN,
            text=rule.text,
            assumption=rule.assumption,
            about=self.quote(rule.trigger),
            element_ids=list(rule.element_ids),
            created_at=run.started_at,
            updated_at=run.started_at,
            run_id=run.id,
        )
        self.questions.append(question)
        self.data.questions.append(question)
        return question

    def answer(self, question: Question, text: str, at: datetime) -> Source:
        source = self.source(
            f"answer/{question.code}",
            SourceKind.ANSWER,
            f"Ответ на {question.code}",
            text,
            at,
            question_id=question.id,
        )
        question.status = QuestionStatus.ANSWERED
        question.answer = Answer(source_id=source.id, text=text)
        question.updated_at = at
        return source

    def ignore(self, question: Question, at: datetime) -> None:
        question.status = QuestionStatus.IGNORED
        question.updated_at = at
        self._touch(at)

    def resolve(self, question: Question, evidence: str, at: datetime) -> None:
        question.status = QuestionStatus.RESOLVED
        question.evidence = self.quote(evidence)
        question.updated_at = at

    def version(self, xml: str, run: Run, trace: Mapping[str, str]) -> Version:
        at = run.finished_at or run.started_at
        quotes = {eid: q for eid, text in trace.items() if (q := self.quote(text))}
        version = build_version(
            version_id=seed_id(f"{self.key}/version/{len(self.versions) + 1}"),
            project_id=self.project.id,
            number=len(self.versions) + 1,
            origin=VersionOrigin.GENERATED,
            xml=xml,
            previous_xml=self.versions[-1].xml if self.versions else None,
            questions=self.questions,
            lint=lint_document(parse_bpmn(xml)),
            xsd_valid=True,
            trace=quotes,
            created_at=at,
            run_id=run.id,
        )
        run.version_id = version.id
        self.versions.append(version)
        self.data.versions.append(version)
        self._touch(at)
        return version


def _rule(text: str) -> QuestionRule:
    return next(rule for rule in pb.PLAYBOOK.questions if rule.text == text)


def _diagram(rules: Iterable[DiagramRule], fixture: str) -> DiagramRule:
    return next(rule for rule in rules if rule.fixture == fixture)


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    """Время сентября 2026 года в UTC."""
    return datetime(2026, 9, day, hour, minute, tzinfo=UTC)


def _seed_demo(data: SeedData) -> None:
    p = _ProjectBuilder(
        data,
        "tp861",
        "Технологическое присоединение к электросетям",
        "Процесс по Правилам ТП (ПП РФ № 861): от заявки до акта и договора энергоснабжения.",
        _at(22, 7),
    )
    p.source(
        "regulation",
        SourceKind.TEXT,
        "Регламент ТП (выжимка из ПП № 861)",
        read_text("tp861_regulation.md"),
        _at(22, 7, 5),
    )
    run1 = p.run("1", RunMode.ANALYZE, _at(22, 7, 10))
    # Q-3 (счёт) и Q-4 (срок дополнения) остаются открытыми: Q-3 решит следующий анализ.
    q_notify, q_boundary, _, _ = (
        p.ask(_rule(text), run1)
        for text in (pb.TP_NOTIFY, pb.TP_BOUNDARY, pb.TP_INVOICE, pb.TP_DEADLINE)
    )
    p.finish_run(run1)
    run2 = p.run("2", RunMode.BUILD, _at(22, 7, 20))
    p.finish_run(run2)
    p.version(read_bpmn("tp861_v1"), run2, _diagram(pb.TP_DIAGRAMS, "tp861_v1").trace)

    p.source(
        "meeting-note",
        SourceKind.VOICE,
        "Заметка со встречи с отделом ТП",
        read_text("tp861_meeting_note.txt"),
        _at(24, 12, 30),
        duration_sec=142.0,
        mime="audio/webm",
    )
    run3 = p.run("3", RunMode.ANALYZE, _at(24, 12, 35))
    p.resolve(q_notify, pb.TP_RESOLUTIONS[0].evidence, run3.started_at)
    q_term = p.ask(_rule(pb.TP_TERM), run3)
    p.ask(_rule(pb.TP_ORDER), run3)
    p.finish_run(run3, resolved=1)

    p.ignore(q_boundary, _at(25, 7, 50))
    run4 = p.run("4", RunMode.BUILD, _at(25, 8))
    p.finish_run(run4)
    p.version(read_bpmn("tp861_v2"), run4, _diagram(pb.TP_DIAGRAMS, "tp861_v2").trace)

    p.answer(q_term, pb.TP_ANSWER_TERM, _at(26, 9, 15))
    finances = read_text("tp861_finances.md")
    p.source(
        "finances",
        SourceKind.FILE,
        "Финансы проекта.docx",
        finances,
        _at(30, 13, 40),
        file_name="Финансы проекта.docx",
        mime=DOCX_MIME,
        size_bytes=1357,
    )


def _seed_rich(data: SeedData) -> None:
    """Четыре проекта с собственными схемами из фикстур."""
    p = _ProjectBuilder(
        data,
        "repair-outage",
        "Вывод линии 110 кВ в плановый ремонт",
        "Диспетчерская заявка собственника и согласование с диспетчерским центром.",
        _at(15, 9),
    )
    p.source(
        "regulation",
        SourceKind.TEXT,
        "Порядок вывода в ремонт",
        read_text("repair_outage.md"),
        _at(15, 9, 5),
    )
    run = p.run("1", RunMode.ANALYZE, _at(15, 9, 10))
    _, refusal, _ = (p.ask(rule, run) for rule in pb.REPAIR_QUESTIONS)
    p.finish_run(run)
    p.ignore(refusal, _at(16, 11))
    build = p.run("2", RunMode.BUILD, _at(16, 11, 5))
    p.finish_run(build)
    p.version(read_bpmn("repair_outage"), build, pb.REPAIR_DIAGRAM.trace)

    p = _ProjectBuilder(
        data,
        "work-permit",
        "Работы в электроустановках по наряду-допуску",
        "Выдача наряда, подготовка рабочего места, допуск бригады и закрытие наряда.",
        _at(10, 6),
    )
    p.source(
        "regulation",
        SourceKind.TEXT,
        "Порядок работы по наряду",
        read_text("work_permit.md"),
        _at(10, 6, 5),
    )
    run = p.run("1", RunMode.ANALYZE, _at(10, 6, 10))
    supervision, remarks = (p.ask(rule, run) for rule in pb.PERMIT_QUESTIONS)
    p.finish_run(run)
    p.answer(remarks, pb.PERMIT_ANSWER_REMARKS, _at(11, 8))
    p.ignore(supervision, _at(11, 8, 5))
    build = p.run("2", RunMode.BUILD, _at(11, 8, 10))
    p.resolve(remarks, pb.PERMIT_ANSWER_REMARKS, build.started_at)
    p.finish_run(build, resolved=1)
    p.version(read_bpmn("work_permit"), build, pb.PERMIT_DIAGRAM.trace)

    p = _ProjectBuilder(
        data,
        "procurement-223",
        "Закупка по 223-ФЗ: запрос котировок",
        "Закупка материалов для ремонтной программы способом запроса котировок.",
        _at(18, 10),
    )
    p.source(
        "regulation",
        SourceKind.FILE,
        "Положение о закупке (выдержка).pdf",
        read_text("procurement_223.md"),
        _at(18, 10, 5),
        file_name="Положение о закупке (выдержка).pdf",
        mime="application/pdf",
        size_bytes=48_213,
    )
    run = p.run("1", RunMode.ANALYZE, _at(18, 10, 10))
    _, plan = (p.ask(rule, run) for rule in pb.PROCUREMENT_QUESTIONS)
    p.finish_run(run)
    build = p.run("2", RunMode.BUILD, _at(18, 10, 20))
    p.finish_run(build)
    p.version(read_bpmn("procurement_223"), build, pb.PROCUREMENT_DIAGRAM.trace)
    p.answer(plan, pb.PROCUREMENT_ANSWER_PLAN, _at(19, 7, 30))

    p = _ProjectBuilder(
        data,
        "supply-contract",
        "Заключение договора энергоснабжения с юрлицом",
        "Заявление потребителя, проверка документов и запрос сведений у сетевой организации.",
        _at(5, 8),
    )
    p.source(
        "regulation",
        SourceKind.TEXT,
        "Порядок заключения договора",
        read_text("supply_contract.md"),
        _at(5, 8, 5),
    )
    run = p.run("1", RunMode.ANALYZE, _at(5, 8, 10))
    grid, package = (p.ask(rule, run) for rule in pb.SUPPLY_QUESTIONS)
    p.finish_run(run)
    p.source(
        "lawyer-call",
        SourceKind.VOICE,
        "Звонок юристу гарантирующего поставщика",
        pb.SUPPLY_NOTE,
        _at(6, 12),
        duration_sec=38.0,
        mime="audio/webm",
    )
    p.ignore(grid, _at(6, 12, 30))
    build = p.run("2", RunMode.BUILD, _at(6, 12, 40))
    p.resolve(package, pb.SUPPLY_RESOLUTIONS[0].evidence, build.started_at)
    p.finish_run(build, resolved=1)
    p.version(read_bpmn("supply_contract"), build, pb.SUPPLY_DIAGRAM.trace)


_FILE_KINDS = (
    ("pdf", "application/pdf"),
    ("docx", DOCX_MIME),
)


def _linear(topic: Topic, steps: Sequence[tuple[str, str]]) -> str:
    return build_linear_diagram(
        process_name=topic.title,
        steps=[LinearStep(name=task, lane=role) for role, task in steps],
        key=topic.key.replace("-", "_"),
    )


def _settle_questions(
    p: _ProjectBuilder,
    questions: Sequence[tuple[Question, str]],
    *,
    ready: bool,
    at: datetime,
    rng: random.Random,
) -> datetime:
    """Статусы вопросов типового проекта: у «готового» нет открытых, у остальных Q-1 открыт."""
    at += timedelta(hours=rng.randint(2, 48))
    for number, (question, answer_text) in enumerate(questions):
        if not ready and number == 0:
            continue
        roll = rng.random()
        if roll < 0.45:  # noqa: PLR2004
            p.ignore(question, at)
        elif roll < 0.8 or ready:  # noqa: PLR2004
            p.answer(question, answer_text, at)
            p.resolve(question, answer_text, at + timedelta(minutes=30))
        else:
            p.answer(question, answer_text, at)
    return at


def _seed_topic(data: SeedData, index: int, topic: Topic, rng: random.Random) -> None:
    created = BASE_TIME - timedelta(days=rng.randint(3, 80), hours=rng.randint(0, 9))
    p = _ProjectBuilder(data, topic.key, topic.title, topic.description, created)
    if index % 6 == 0:
        return  # пустой проект: источников ещё нет

    at = created + timedelta(minutes=rng.randint(5, 50))
    text = regulation_text(topic)
    if rng.random() < 0.5:  # noqa: PLR2004
        p.source("regulation", SourceKind.TEXT, f"Регламент: {topic.title}", text, at)
    else:
        extension, mime = rng.choice(_FILE_KINDS)
        name = f"Регламент — {topic.title}.{extension}"
        p.source(
            "regulation",
            SourceKind.FILE,
            name,
            text,
            at,
            file_name=name,
            mime=mime,
            size_bytes=len(text.encode()) * rng.randint(9, 30),
        )
    if index == 7:  # noqa: PLR2004 — один проект показывает источник, который не удалось разобрать
        p.source(
            "scan",
            SourceKind.FILE,
            "Скан приказа.pdf",
            "",
            at + timedelta(minutes=3),
            status=SourceStatus.FAILED,
            error="Не удалось извлечь текст: в PDF нет текстового слоя",
            file_name="Скан приказа.pdf",
            mime="application/pdf",
            size_bytes=2_418_112,
        )
    if index == 9:  # noqa: PLR2004 — один проект показывает выключенный источник
        p.source(
            "old",
            SourceKind.TEXT,
            "Старая редакция регламента",
            text.replace("Порядок действий:", "Порядок действий (редакция 2023 года):"),
            at - timedelta(days=30),
            active=False,
        )
    if rng.random() < 0.4:  # noqa: PLR2004
        at += timedelta(hours=rng.randint(1, 30))
        p.source(
            "note",
            SourceKind.VOICE,
            "Заметка после разговора",
            meeting_note(topic),
            at,
            duration_sec=float(rng.randint(25, 160)),
            mime="audio/webm",
        )

    ready = rng.random() < 0.5  # noqa: PLR2004
    at += timedelta(minutes=rng.randint(5, 90))
    run = p.run("1", RunMode.ANALYZE, at)
    tasks = [task for _, task in topic.steps]
    generic = generic_questions(tasks)[: rng.randint(2, 4)]
    questions = [(p.ask(item.rule, run), item.answer) for item in generic]
    p.finish_run(run)

    at = _settle_questions(p, questions, ready=ready, at=at, rng=rng)

    if ready or rng.random() < 0.5:  # noqa: PLR2004
        versions = rng.randint(1, 2) if ready else 1
        for number in range(versions):
            at += timedelta(hours=rng.randint(1, 20))
            build = p.run(f"build-{number + 1}", RunMode.BUILD, at)
            p.finish_run(build)
            steps = topic.steps if number == versions - 1 else topic.steps[:-1]
            trace = {f"Task_{i}": task for i, (_, task) in enumerate(steps, start=1)}
            p.version(_linear(topic, steps), build, trace)


def build_seed() -> SeedData:
    data = SeedData()
    rng = random.Random(SEED)  # noqa: S311 — детерминированные демо-данные, не криптография
    _seed_demo(data)
    _seed_rich(data)
    for index, topic in enumerate(TOPICS):
        _seed_topic(data, index, topic, rng)
    return data
