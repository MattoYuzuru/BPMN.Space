"""Юнит-тесты domain: вопросы, сверка, статусы, курсор, BPMN (дифф, линтер, разбор)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.domain.analysis import AnalysisResult, ContextSource, NewQuestion, QuestionUpdate
from app.domain.bpmn.diff import diff_documents
from app.domain.bpmn.document import BpmnFormatError, parse_bpmn
from app.domain.bpmn.lint import lint_document
from app.domain.models import (
    Answer,
    ProjectStatus,
    Question,
    QuestionKind,
    QuestionStatus,
    Quote,
    RunMode,
    RunStage,
    RunStatus,
    Severity,
    SourceKind,
)
from app.domain.pagination import Cursor, InvalidCursorError
from app.domain.projects import default_source_title, derive_status
from app.domain.questions import (
    QuestionTransitionError,
    answer,
    drop_answer,
    ignore,
    next_code,
    normalize,
    project_summary,
    quote_in_source,
    reconcile,
    reopen,
)
from app.domain.runs import progress_at, stage_label, stages_for
from app.fixtures import read_bpmn

NOW = datetime(2026, 10, 1, tzinfo=UTC)
PROJECT = uuid.uuid4()


def _question(code: str = "Q-1", status: QuestionStatus = QuestionStatus.OPEN) -> Question:
    return Question(
        id=uuid.uuid4(),
        project_id=PROJECT,
        code=code,
        kind=QuestionKind.MISSING_ACTOR,
        severity=Severity.MAJOR,
        status=status,
        text=f"Вопрос {code}",
        assumption="Допущение",
        created_at=NOW,
        updated_at=NOW,
    )


def _source(content: str) -> ContextSource:
    return ContextSource(
        id=uuid.uuid4(),
        kind=SourceKind.TEXT,
        title="Источник",
        content=content,
        created_at=NOW + timedelta(hours=1),
    )


def test_answer_ignore_reopen_transitions() -> None:
    question = _question()
    source_id = uuid.uuid4()
    answer(question, source_id=source_id, text="Ответ", now=NOW)
    assert question.status is QuestionStatus.ANSWERED
    with pytest.raises(QuestionTransitionError, match="отвечен"):
        ignore(question, now=NOW)
    assert reopen(question, now=NOW) == source_id
    assert question.answer is None
    ignore(question, now=NOW)
    with pytest.raises(QuestionTransitionError):
        answer(question, source_id=source_id, text="x", now=NOW)
    assert reopen(question, now=NOW) is None
    with pytest.raises(QuestionTransitionError):
        reopen(question, now=NOW)


def test_drop_answer_reopens_answered_only() -> None:
    answered = _question(status=QuestionStatus.ANSWERED)
    drop_answer(answered, now=NOW)
    assert answered.status is QuestionStatus.OPEN
    resolved = _question(status=QuestionStatus.RESOLVED)
    drop_answer(resolved, now=NOW)
    assert resolved.status is QuestionStatus.RESOLVED


def test_next_code_and_normalize() -> None:
    assert next_code([]) == "Q-1"
    assert next_code([_question("Q-2"), _question("Q-10"), _question("X")]) == "Q-11"
    assert normalize("  «Ёлка»\n  Зелёная ") == '"елка" зеленая'
    assert quote_in_source("ЗЕЛЕНАЯ ёлка", "Стоит зелёная  елка.")
    assert not quote_in_source("   ", "что угодно")


def test_reconcile_requires_real_quote() -> None:
    source = _source("Счёт формирует финансовый отдел.")
    open_q = _question("Q-1")
    answered = _question("Q-2", QuestionStatus.ANSWERED)
    ignored = _question("Q-3", QuestionStatus.IGNORED)
    analysis = AnalysisResult(
        question_updates=[
            QuestionUpdate(
                code="Q-1",
                status=QuestionStatus.RESOLVED,
                evidence=Quote(source_id=source.id, quote="финансовый отдел"),
            ),
            QuestionUpdate(
                code="Q-2",
                status=QuestionStatus.RESOLVED,
                evidence=Quote(source_id=source.id, quote="выдуманная цитата"),
            ),
            QuestionUpdate(code="Q-3", status=QuestionStatus.OPEN),
            QuestionUpdate(code="Q-9", status=QuestionStatus.RESOLVED),
        ],
        new_questions=[
            NewQuestion(
                kind=QuestionKind.CONFLICT,
                severity=Severity.BLOCKER,
                text="Новый вопрос",
                assumption="Допущение",
                about=Quote(source_id=source.id, quote="нет такой цитаты"),
            ),
            NewQuestion(
                kind=QuestionKind.MISSING_ACTOR,
                severity=Severity.MINOR,
                text="вопрос Q-1",  # дубль существующего
                assumption="—",
            ),
        ],
    )
    run_id = uuid.uuid4()
    outcome = reconcile(
        [open_q, answered, ignored],
        analysis,
        [source],
        project_id=PROJECT,
        run_id=run_id,
        now=NOW,
        new_id=uuid.uuid4,
    )
    assert [q.code for q in outcome.changed] == ["Q-1"]
    assert open_q.status is QuestionStatus.RESOLVED
    assert answered.status is QuestionStatus.ANSWERED
    assert len(outcome.rejected) == 3
    assert [q.code for q in outcome.created] == ["Q-4"]
    assert outcome.created[0].about is None
    assert outcome.summary.resolved == 1
    assert outcome.summary.new == 1
    assert outcome.summary.answered == 1
    assert outcome.summary.ignored == 1

    summary = project_summary([open_q, answered, ignored, *outcome.created], latest_run_id=run_id)
    assert (summary.resolved, summary.open, summary.new) == (1, 0, 1)


def test_reconcile_answered_back_to_open_preserves_answer_history() -> None:
    answered = _question("Q-1", QuestionStatus.ANSWERED)
    answer_id = uuid.uuid4()
    answered.answer = Answer(source_id=answer_id, text="Не знаю")
    outcome = reconcile(
        [answered],
        AnalysisResult(
            question_updates=[
                QuestionUpdate(
                    code="Q-1", status=QuestionStatus.OPEN, reason="Ответ не указал исполнителя"
                )
            ]
        ),
        [],
        project_id=PROJECT,
        run_id=uuid.uuid4(),
        now=NOW,
        new_id=uuid.uuid4,
    )
    assert answered.status is QuestionStatus.OPEN
    assert outcome.summary.open == 1
    assert answered.answer == Answer(source_id=answer_id, text="Не знаю")


def test_exact_question_text_does_not_merge_different_source_contexts() -> None:
    first, second = _source("Согласовать заявку."), _source("Согласовать счёт.")
    old = _question()
    old.about = Quote(source_id=first.id, quote=first.content)
    result = reconcile(
        [old],
        AnalysisResult(
            new_questions=[
                NewQuestion(
                    text=old.text,
                    kind=old.kind,
                    severity=old.severity,
                    assumption="Не определён",
                    about=Quote(source_id=second.id, quote=second.content),
                )
            ]
        ),
        [first, second],
        project_id=PROJECT,
        run_id=uuid.uuid4(),
        now=NOW,
        new_id=uuid.uuid4,
    )
    assert len(result.created) == 1
    assert result.created[0].about == Quote(source_id=second.id, quote=second.content)


def test_derive_status() -> None:
    assert derive_status(has_sources=False, open_questions=0, active_run_mode=None) == "empty"
    assert derive_status(has_sources=True, open_questions=2, active_run_mode=None) == (
        ProjectStatus.NEEDS_ANSWERS
    )
    assert derive_status(has_sources=True, open_questions=0, active_run_mode=None) == "ready"
    assert derive_status(has_sources=True, open_questions=0, active_run_mode=RunMode.BUILD) == (
        ProjectStatus.BUILDING
    )
    assert derive_status(has_sources=True, open_questions=0, active_run_mode=RunMode.ANALYZE) == (
        ProjectStatus.ANALYZING
    )


def test_default_source_title() -> None:
    assert default_source_title("\n# Заголовок\nтекст") == "Заголовок"
    long = "слово " * 30
    title = default_source_title(long)
    assert title.endswith("…")
    assert len(title) <= 61


def test_cursor_roundtrip_and_errors() -> None:
    cursor = Cursor(updated_at=NOW, id=PROJECT)
    assert Cursor.decode(cursor.encode()) == cursor
    for bad in ("", "!!!", "e30", "bm90LWpzb24"):
        with pytest.raises(InvalidCursorError):
            Cursor.decode(bad)


def test_stages_and_labels() -> None:
    assert len(stages_for(RunMode.ANALYZE)) == 3
    assert stages_for(RunMode.BUILD)[-1] is RunStage.LAYOUT
    assert progress_at(RunMode.BUILD, RunStage.READING_SOURCES) == 0
    assert progress_at(RunMode.ANALYZE, RunStage.RECONCILING) == 0.667
    assert stage_label(RunStatus.QUEUED, None) == "В очереди"
    assert stage_label(RunStatus.RUNNING, RunStage.LAYOUT) == "Раскладываю схему"
    assert stage_label(RunStatus.SUCCEEDED, RunStage.LAYOUT) == "Готово"
    assert stage_label(RunStatus.FAILED, None) == "Ошибка"


def test_diff_between_demo_versions() -> None:
    v1, v2, v3 = (parse_bpmn(read_bpmn(f"tp861_v{n}")) for n in (1, 2, 3))
    assert diff_documents(None, v1).added == len(v1.element_ids)
    assert (diff_documents(v1, v2).added, diff_documents(v1, v2).changed) == (3, 2)
    assert diff_documents(v3, v2).removed == 3


def test_lint_rules() -> None:
    xml = """<?xml version="1.0"?>
<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL" id="d" targetNamespace="x">
  <process id="p">
    <task id="t1"/>
    <exclusiveGateway id="g"/>
    <task id="t2" name="Шаг"/>
    <sequenceFlow id="f1" sourceRef="t1" targetRef="t2"/>
    <sequenceFlow id="f2" sourceRef="g" targetRef="t2"/>
  </process>
</definitions>"""
    rules = {(i.rule, i.element_id) for i in lint_document(parse_bpmn(xml))}
    assert ("start-event-required", None) in rules
    assert ("end-event-required", None) in rules
    assert ("label-required", "t1") in rules
    assert ("label-required", "g") not in rules  # не разветвляющийся шлюз
    assert ("fake-join", "t2") in rules
    assert ("no-implicit-start", "t1") in rules
    assert ("no-implicit-end", "t2") in rules
    assert not parse_bpmn(xml).has_layout


def test_parse_errors() -> None:
    with pytest.raises(BpmnFormatError, match="строка 1"):
        parse_bpmn("<a>")
    with pytest.raises(BpmnFormatError, match="процесса"):
        parse_bpmn(
            '<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL" targetNamespace="x"/>'
        )
