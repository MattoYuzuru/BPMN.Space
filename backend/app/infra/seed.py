"""Детерминированные общие демо-проекты: два коротких учебных и три комплексных.

ТП сохраняет исторический сценарий анализа с вопросами и тремя версиями. Наряд-допуск
показывает AND и цикл. Подробные сценарии энергетики, логистики и выпуска сервиса содержат
44–49 узлов и подтверждённые текстами переходы. Графы записаны как фикстуры, без живой LLM.
UUID общих проектов стабильны. Старые демонстрационные UUID скрываются при startup seed;
пользовательские проекты и копии не перезаписываются.
"""

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid5

from app.domain.analysis import ContextSource
from app.domain.bpmn.document import parse_bpmn
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
from app.fixtures import FIXTURES_DIR, read_bpmn, read_text
from app.fixtures import playbook as pb
from app.fixtures.catalog import TOPICS
from app.fixtures.complex_examples import COMPLEX_EXAMPLES
from app.fixtures.types import DiagramRule, QuestionRule

NAMESPACE = UUID("6f0c2d4e-8a51-4c1e-9b7a-0d3e5f861000")
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
    retired_project_ids: tuple[UUID, ...] = ()


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


def _seed_permit(data: SeedData) -> None:
    """Короткий сценарий: параллельная подготовка и цикл устранения замечаний."""
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


def _seed_complex(data: SeedData) -> None:
    for index, example in enumerate(COMPLEX_EXAMPLES):
        at = _at(20 - index, 8)
        p = _ProjectBuilder(data, example.key, example.title, example.description, at)
        p.source(
            "regulation",
            SourceKind.TEXT,
            "Подробный порядок процесса",
            read_text(f"{example.fixture}.md"),
            at + timedelta(minutes=5),
        )
        graph = json.loads((FIXTURES_DIR / "ir" / f"{example.fixture}.json").read_text())
        trace = {node["id"]: node["name"] for node in graph["nodes"] if node["type"] == "task"}
        p.source(
            "decisions",
            SourceKind.TEXT,
            "Правила ветвления и завершения",
            "Условия выбора и роли зафиксированы в подробном порядке. "
            "Все ветви AND обязательны; XOR выполняет ровно один выбранный исход. "
            "Повторная проверка продолжается после исправления замечаний. "
            "Завершённый случай не открывается повторно: новый случай создаёт новый экземпляр.",
            at + timedelta(minutes=7),
        )
        p.source(
            "handover",
            SourceKind.TEXT,
            "Памятка исполнителям",
            "Каждый исполнитель сохраняет подтверждения в карточке случая. "
            "Заместителя назначает руководитель роли; при его отсутствии этап ожидает назначения. "
            "Скорость экранного воспроизведения не задаёт длительность бизнес-операций. "
            "Это вымышленный учебный сценарий, а не нормативный регламент.",
            at + timedelta(minutes=9),
        )
        build = p.run("1", RunMode.BUILD, at + timedelta(minutes=10))
        build.ir = graph
        p.finish_run(build)
        p.version(read_bpmn(example.fixture), build, trace)


def build_seed() -> SeedData:
    """Пять общих примеров; прежние встроенные UUID скрываются без удаления истории."""
    data = SeedData(
        retired_project_ids=tuple(
            seed_id(f"project/{key}")
            for key in (
                "repair-outage",
                "procurement-223",
                "supply-contract",
                *(topic.key for topic in TOPICS),
            )
        )
    )
    _seed_demo(data)
    _seed_permit(data)
    _seed_complex(data)
    return data
