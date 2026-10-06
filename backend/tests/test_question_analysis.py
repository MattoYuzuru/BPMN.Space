"""Контракт реального адаптера вопросов: записанные ответы без платных запросов модели."""

import asyncio
import json
from collections.abc import Callable
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.config import Settings
from app.container import build_container
from app.domain.analysis import ContextSource, RunContext
from app.domain.models import (
    Answer,
    Question,
    QuestionKind,
    QuestionStatus,
    Quote,
    RunMode,
    RunStage,
    RunStatus,
    Severity,
    Source,
    SourceKind,
    SourceStatus,
)
from app.domain.questions import reconcile
from app.fixtures import read_bpmn
from app.llm.base import OutputTruncatedError, PipelineError
from app.llm.openai_compatible import OpenAICompatiblePipeline
from app.llm.question_analysis import snapshot_fingerprint

NOW = datetime(2026, 10, 6, tzinfo=UTC)
type Response = Callable[[dict[str, Any]], dict[str, Any]]


def _source(text: str, kind: SourceKind = SourceKind.TEXT) -> ContextSource:
    return ContextSource(id=uuid4(), kind=kind, title="Регламент", content=text, created_at=NOW)


def _question(code: str = "Q-1", status: QuestionStatus = QuestionStatus.OPEN) -> Question:
    return Question(
        id=uuid4(),
        project_id=uuid4(),
        code=code,
        kind=QuestionKind.MISSING_ACTOR,
        severity=Severity.BLOCKER,
        status=status,
        text="Кто готовит проект акта?",
        assumption="Акт готовит заявитель",
        created_at=NOW,
        updated_at=NOW,
    )


def _context(sources: list[ContextSource], questions: list[Question] | None = None) -> RunContext:
    return RunContext(
        project_id=uuid4(),
        project_title="Присоединение",
        sources=sources,
        evidence_sources=deepcopy(sources),
        questions=deepcopy(questions or []),
    )


def _analysis(
    payload: dict[str, Any],
    *,
    updates: list[dict[str, Any]] | None = None,
    new: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    by_code = {item["code"]: item for item in updates or []}
    return {
        "complete": True,
        "question_updates": [
            by_code.get(item["key"], {"code": item["key"], "status": "keep"})
            for item in payload["existing_questions"]
        ],
        "new_questions": new or [],
    }


def _candidate(
    source: ContextSource,
    text: str = "Кто оформляет акт?",
    *,
    kind: str = "missing_actor",
    elements: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "severity": "blocker",
        "text": text,
        "assumption": "Исполнитель ещё не определён",
        "source_id": str(source.id),
        "quote": source.content,
        "element_ids": elements or [],
    }


def _resolution(source: ContextSource, code: str = "Q-1") -> dict[str, Any]:
    return {
        "code": code,
        "status": "resolved",
        "evidence": {"source_id": str(source.id), "quote": source.content},
        "reason": "Указаны действие и его исполнитель",
    }


class RecordedProvider:
    def __init__(self, analyze: Response, verify: Response | None = None) -> None:
        self.analyze = analyze
        self.verify = verify
        self.requests: list[dict[str, Any]] = []
        self.sizes: list[int] = []

    def __call__(self, system: str, prompt: str) -> str:
        payload = json.loads(prompt)
        self.requests.append(payload)
        self.sizes.append(len(system) + len(prompt))
        if payload["phase"] == "analyze":
            response = self.analyze(payload)
        elif self.verify:
            response = self.verify(payload)
        else:
            response = {
                "complete": True,
                "decisions": [
                    {
                        "id": item["id"],
                        "valid": True,
                        "reason": "Проверены действие, исполнитель и контекст источника",
                    }
                    for item in payload["proposals"]
                ],
            }
        return json.dumps(response, ensure_ascii=False)

    def pipeline(self) -> OpenAICompatiblePipeline:
        return OpenAICompatiblePipeline(api_key="recorded-only", complete=self)


@pytest.mark.parametrize("kind", [SourceKind.FILE, SourceKind.VOICE, SourceKind.ANSWER])
@pytest.mark.parametrize(
    "status", [QuestionStatus.OPEN, QuestionStatus.ANSWERED, QuestionStatus.IGNORED]
)
async def test_every_old_question_can_resolve_from_documents_and_neighbor_answers(
    kind, status
) -> None:
    evidence = _source("Проект акта готовит инженер, выезжавший на осмотр.", kind)
    question = _question(status=status)
    neighbor = _question("Q-2", QuestionStatus.ANSWERED)
    neighbor.answer = Answer(source_id=evidence.id, text=evidence.content)
    question.answer = Answer(source_id=uuid4(), text="Мой прежний неполный ответ")
    provider = RecordedProvider(lambda p: _analysis(p, updates=[_resolution(evidence)]))
    context = _context([evidence], [question, neighbor])

    result = await provider.pipeline().analyze(context)
    outcome = reconcile(
        context.questions,
        result,
        context.evidence_sources or [],
        project_id=context.project_id,
        run_id=uuid4(),
        now=NOW,
        new_id=uuid4,
    )

    assert [q.code for q in outcome.changed] == ["Q-1"]
    assert context.questions[0].status is QuestionStatus.RESOLVED
    assert context.questions[0].evidence == Quote(source_id=evidence.id, quote=evidence.content)
    assert context.questions[0].answer == question.answer
    request = provider.requests[0]
    assert [q["key"] for q in request["existing_questions"]] == ["Q-1", "Q-2"]
    assert request["existing_questions"][1]["answer_source_id"] == str(evidence.id)
    assert request["sources"][0]["id"] == str(evidence.id)
    assert result.audit["model_calls"] == 2


async def test_literal_but_irrelevant_quote_does_not_resolve_question() -> None:
    source = _source("Инженер участвует во встрече. Проект акта не обсуждали.")
    provider = RecordedProvider(
        lambda p: _analysis(p, updates=[_resolution(source)]),
        lambda p: {
            "complete": True,
            "decisions": [
                {
                    "id": item["id"],
                    "valid": False,
                    "reason": "Участие инженера во встрече не означает подготовку акта",
                }
                for item in p["proposals"]
            ],
        },
    )
    result = await provider.pipeline().analyze(_context([source], [_question()]))
    assert result.question_updates == []
    assert "не означает подготовку" in result.warnings[0]
    assert provider.requests[1]["proposals"][0]["proof_context"] == source.content


@pytest.mark.parametrize("invalid", ["invented", "foreign", "missing"])
async def test_invented_or_unknown_source_evidence_is_rejected_before_semantic_check(
    invalid,
) -> None:
    source = _source("Инженер готовит акт.")
    update = _resolution(source)
    if invalid == "invented":
        update["evidence"]["quote"] = "Заявитель готовит акт."
    elif invalid == "foreign":
        update["evidence"]["source_id"] = str(uuid4())
    else:
        update["evidence"] = None
    provider = RecordedProvider(lambda p: _analysis(p, updates=[update]))
    result = await provider.pipeline().analyze(_context([source], [_question()]))
    assert not result.question_updates
    assert "цитата не найдена" in result.warnings[0]
    assert len(provider.requests) == 1


async def test_insufficient_answer_reopens_with_reason_and_preserves_history() -> None:
    source = _source("Не знаю", SourceKind.ANSWER)
    question = _question(status=QuestionStatus.ANSWERED)
    question.answer = Answer(source_id=source.id, text=source.content)
    provider = RecordedProvider(
        lambda p: _analysis(
            p,
            updates=[
                {"code": "Q-1", "status": "open", "reason": "Ответ не содержит исполнителя акта"}
            ],
        )
    )
    context = _context([source], [question])
    result = await provider.pipeline().analyze(context)
    reconcile(
        context.questions,
        result,
        [source],
        project_id=context.project_id,
        run_id=uuid4(),
        now=NOW,
        new_id=uuid4,
    )
    assert context.questions[0].status is QuestionStatus.OPEN
    assert context.questions[0].answer == question.answer
    assert result.question_updates[0].reason == "Ответ не содержит исполнителя акта"


@pytest.mark.parametrize("status", [QuestionStatus.OPEN, QuestionStatus.ANSWERED])
async def test_resolved_update_and_matching_known_fact_candidate_create_no_duplicate(
    status,
) -> None:
    source = _source("Проект акта готовит инженер.", SourceKind.ANSWER)
    old = _question(status=status)
    if status is QuestionStatus.ANSWERED:
        old.answer = Answer(source_id=source.id, text=source.content)

    def verify(payload):
        return {
            "complete": True,
            "decisions": [
                {
                    "id": p["id"],
                    "valid": True,
                    "reason": "Факт отвечает именно на вопрос о подготовке акта",
                    **({"same_as": "Q-1", "relation": "known_fact"} if "kind" in p else {}),
                }
                for p in payload["proposals"]
            ],
        }

    provider = RecordedProvider(
        lambda p: _analysis(
            p,
            updates=[_resolution(source)],
            new=[_candidate(source, "Какой сотрудник готовит акт?")],
        ),
        verify,
    )
    context = _context([source], [old])
    result = await provider.pipeline().analyze(context)
    assert len(result.question_updates) == 1
    assert result.question_updates[0].status is QuestionStatus.RESOLVED
    assert result.new_questions == []
    assert context.questions[0] == old  # snapshot не меняется до guarded application


async def test_semantic_paraphrases_converge_without_five_question_limit() -> None:
    source = _source("Восемь разных объектов обрабатываются без указания исполнителей.")
    candidates = [_candidate(source, f"Кто выполняет этап {i}?") for i in range(8)]
    duplicate = _candidate(source, "Какой сотрудник отвечает за этап 0?")

    def verify(payload):
        decisions = []
        for proposal in payload["proposals"]:
            item = {"id": proposal["id"], "valid": True, "reason": "Сопоставлены объект и этап"}
            index = 0 if "сотрудник" in proposal["text"] else int(proposal["text"].split()[-1][:-1])
            existing = next(
                (q for q in payload["existing_items"] if q["key"] == f"Q-{index + 1}"), None
            )
            if existing:
                item.update(same_as=existing["key"], relation="duplicate")
            elif "сотрудник" in proposal["text"]:
                item.update(same_as="N-1", relation="duplicate")
            decisions.append(item)
        return {"complete": True, "decisions": decisions}

    provider = RecordedProvider(lambda p: _analysis(p, new=[*candidates, duplicate]), verify)
    pipeline = provider.pipeline()
    first_context = _context([source])
    first = await pipeline.analyze(first_context)
    assert len(first.new_questions) == 8
    created = reconcile(
        [],
        first,
        [source],
        project_id=first_context.project_id,
        run_id=uuid4(),
        now=NOW,
        new_id=uuid4,
    ).created
    next_context = replace(first_context, questions=created)
    second = await pipeline.analyze(next_context)
    assert second.new_questions == []
    assert second.question_updates == []
    third = await pipeline.analyze(deepcopy(next_context))
    assert third.audit["cache_hit"] is True
    assert third.audit["model_calls"] == 0
    assert len(provider.requests) == 4
    fresh = _source("Девятый объект появился в новом документе без исполнителя.")
    candidates.append(_candidate(fresh, "Кто выполняет этап 8?"))
    with_new_source = replace(next_context, evidence_sources=[source, fresh])
    additional = await pipeline.analyze(with_new_source)
    assert [q.text for q in additional.new_questions] == ["Кто выполняет этап 8?"]


async def test_different_objects_and_kinds_are_not_merged_by_generic_text_match() -> None:
    source = _source("Кто согласует заявку и кто согласует счёт, не указано.")
    old = _question()
    old.element_ids = ["Task_Request"]
    candidates = [
        _candidate(source, old.text, elements=["Task_Invoice"]),
        _candidate(source, "При каком условии согласуется заявка?", kind="ambiguous_condition"),
    ]
    provider = RecordedProvider(
        lambda p: _analysis(p, new=candidates),
        lambda p: {
            "complete": True,
            "decisions": [
                {
                    "id": item["id"],
                    "valid": True,
                    "same_as": "Q-1",
                    "relation": "duplicate",
                    "reason": "Общие слова похожи",
                }
                for item in p["proposals"]
            ],
        },
    )
    context = _context([source], [old])
    result = await provider.pipeline().analyze(context)
    assert len(result.new_questions) == 2
    outcome = reconcile(
        context.questions,
        result,
        [source],
        project_id=context.project_id,
        run_id=uuid4(),
        now=NOW,
        new_id=uuid4,
    )
    assert len(outcome.created) == 2


async def test_contradiction_links_new_question_without_overwriting_resolved_history() -> None:
    old_source = _source("Проект акта готовит инженер.")
    new_source = _source("Новый регламент: проект акта готовит бухгалтерия.")
    old = _question(status=QuestionStatus.RESOLVED)
    old.evidence = Quote(source_id=old_source.id, quote=old_source.content)
    old.answer = Answer(source_id=old_source.id, text=old_source.content)
    provider = RecordedProvider(
        lambda p: _analysis(
            p,
            new=[
                _candidate(new_source, "Кто готовит акт после смены регламента?", kind="conflict")
            ],
        ),
        lambda p: {
            "complete": True,
            "decisions": [
                {
                    "id": item["id"],
                    "valid": True,
                    "same_as": "Q-1",
                    "relation": "contradiction",
                    "reason": "Регламенты расходятся",
                }
                for item in p["proposals"]
            ],
        },
    )
    context = _context([old_source, new_source], [old])
    result = await provider.pipeline().analyze(context)
    outcome = reconcile(
        context.questions,
        result,
        context.evidence_sources or [],
        project_id=context.project_id,
        run_id=uuid4(),
        now=NOW,
        new_id=uuid4,
    )
    assert context.questions[0] == old
    assert outcome.changed == []
    assert "Q-1" in outcome.created[0].text
    assert outcome.created[0].kind is QuestionKind.CONFLICT


@pytest.mark.parametrize("full_diagram", [False, True])
async def test_obsolete_requires_removal_evidence_and_complete_diagram(full_diagram) -> None:
    source = _source("Этап оформления акта исключён из данного процесса.")
    update = {**_resolution(source), "status": "obsolete", "reason": "Этап исключён регламентом"}
    provider = RecordedProvider(
        lambda p: _analysis(p, updates=[update]),
        lambda p: {
            "complete": True,
            "decisions": [
                {
                    "id": item["id"],
                    "valid": True,
                    "subject_removed": True,
                    "reason": "Проверено явное исключение этапа",
                }
                for item in p["proposals"]
            ],
        },
    )
    context = _context([source], [_question()])
    context.current_xml = read_bpmn("tp861_v2") if full_diagram else None
    result = await provider.pipeline().analyze(context)
    assert bool(result.question_updates) is full_diagram
    if not full_diagram:
        assert "не доказано" in result.warnings[0]
    else:
        outcome = reconcile(
            context.questions,
            result,
            [source],
            project_id=context.project_id,
            run_id=uuid4(),
            now=NOW,
            new_id=uuid4,
        )
        assert outcome.changed[0].status is QuestionStatus.OBSOLETE
        assert outcome.changed[0].evidence == Quote(source_id=source.id, quote=source.content)


async def test_cached_obsolete_is_invalidated_by_pending_source_and_incomplete_input_flag() -> None:
    source = _source("Этап оформления акта исключён из процесса.")
    update = {**_resolution(source), "status": "obsolete", "reason": "Исключён этап оформления"}
    provider = RecordedProvider(
        lambda p: _analysis(p, updates=[update]),
        lambda p: {
            "complete": True,
            "decisions": [
                {
                    "id": p["id"],
                    "valid": True,
                    "subject_removed": True,
                    "reason": "Явное основание исключения",
                }
                for p in p["proposals"]
            ],
        },
    )
    pipeline = provider.pipeline()
    context = replace(
        _context([source], [_question()]),
        current_xml=read_bpmn("tp861_v2"),
        source_snapshot_hash="ready-snapshot",
    )
    assert (await pipeline.analyze(context)).question_updates
    pending = replace(
        context, source_snapshot_hash="with-processing-source", analysis_input_complete=False
    )
    result = await pipeline.analyze(pending)
    assert not result.question_updates
    assert result.audit["cache_hit"] is False
    assert len(provider.requests) == 4
    assert provider.requests[-1]["source_context_complete"] is False


async def test_all_large_source_tails_and_answers_are_scanned_with_actual_json_overhead() -> None:
    early = _source(('Начало "строки".\n' * 3000) + " Последний факт: инженер готовит акт.")
    neighbor = _source("Бухгалтер проверяет счета.", SourceKind.ANSWER)
    question = _question()

    def analyze(payload):
        tail = any("Последний факт" in s["text"] for s in payload["sources"])
        update = _resolution(replace(early, content="Последний факт: инженер готовит акт."))
        return _analysis(payload, updates=[update] if tail else [])

    provider = RecordedProvider(analyze)
    context = _context([early, neighbor], [question])
    context.sources = [replace(early, content=early.content[:100])]  # урезанный structure контекст
    context.analysis_budget_chars = 20_000
    result = await provider.pipeline().analyze(context)
    assert [u.code for u in result.question_updates] == ["Q-1"]
    sources = [s for p in provider.requests if p["phase"] == "analyze" for s in p["sources"]]
    assert str(neighbor.id) in {s["id"] for s in sources}
    pieces = sorted((s for s in sources if s["id"] == str(early.id)), key=lambda s: s["offset"])
    assert "".join(s["text"] for s in pieces) == early.content
    assert max(provider.sizes) <= context.analysis_budget_chars


async def test_truncated_provider_response_is_split_and_not_silently_accepted() -> None:
    source = _source("Два этапа без исполнителей.")

    def analyze(payload):
        if len(payload["existing_questions"]) > 1:
            raise OutputTruncatedError("JSON обрезан")
        return _analysis(payload)

    provider = RecordedProvider(analyze)
    result = await provider.pipeline().analyze(_context([source], [_question(), _question("Q-2")]))
    assert result.audit["model_calls"] == 3
    assert {p["existing_questions"][0]["key"] for p in provider.requests[1:]} == {"Q-1", "Q-2"}
    assert not result.question_updates


async def test_minimal_truncation_and_missing_old_question_fail_without_partial_results() -> None:
    source = _source("Проект акта готовит инженер.")
    provider = RecordedProvider(
        lambda p: {"complete": False, "question_updates": [], "new_questions": []}
    )
    with pytest.raises(PipelineError, match="минимальной порции"):
        await provider.pipeline().analyze(_context([source], [_question()]))
    missing = RecordedProvider(
        lambda p: {"complete": True, "question_updates": [], "new_questions": []}
    )
    with pytest.raises(PipelineError, match="все прежние вопросы"):
        await missing.pipeline().analyze(_context([source], [_question()]))


async def test_verification_truncation_is_split_until_all_proposals_are_verified() -> None:
    source = _source("Восемь разных этапов без исполнителей.")

    def verify(payload):
        if len(payload["proposals"]) > 1:
            return {"complete": False, "decisions": []}
        return {
            "complete": True,
            "decisions": [
                {
                    "id": payload["proposals"][0]["id"],
                    "valid": True,
                    "reason": "Пробел относится к отдельному этапу",
                }
            ],
        }

    provider = RecordedProvider(
        lambda p: _analysis(
            p, new=[_candidate(source, f"Кто выполняет этап {i}?") for i in range(8)]
        ),
        verify,
    )
    result = await provider.pipeline().analyze(_context([source]))
    assert len(result.new_questions) == 8
    assert result.audit["model_calls"] == 16


async def test_schema_repair_is_bounded_and_audited() -> None:
    attempts = 0

    def analyze(payload):
        nonlocal attempts
        attempts += 1
        return _analysis(payload) if attempts > 1 else {"complete": "yes"}

    provider = RecordedProvider(analyze)
    result = await provider.pipeline().analyze(_context([_source("Полный регламент")]))
    assert "repair" in provider.requests[1]
    assert result.audit["model_calls"] == 2
    invalid = RecordedProvider(lambda p: {"complete": "yes"})
    with pytest.raises(PipelineError, match="по схеме"):
        await invalid.pipeline().analyze(_context([]))
    assert len(invalid.requests) == 2


async def test_tiny_context_budget_fails_before_any_model_request() -> None:
    provider = RecordedProvider(_analysis)
    context = replace(_context([_source("Регламент")]), analysis_budget_chars=2000)
    with pytest.raises(PipelineError, match="бюджет контекста"):
        await provider.pipeline().analyze(context)
    assert provider.requests == []


@pytest.mark.parametrize(
    ("same_as", "relation"),
    [("Q-999", "duplicate"), ("N-1", "duplicate"), (None, "duplicate"), ("Q-1", "new")],
)
async def test_semantic_verification_rejects_unknown_self_or_inconsistent_links(
    same_as, relation
) -> None:
    source = _source("После проверки оформляют акт без указания исполнителя.")
    provider = RecordedProvider(
        lambda p: _analysis(p, new=[_candidate(source)]),
        lambda p: {
            "complete": True,
            "decisions": [
                {
                    "id": item["id"],
                    "valid": True,
                    "same_as": same_as,
                    "relation": relation,
                    "reason": "Предложена связь",
                }
                for item in p["proposals"]
            ],
        },
    )
    with pytest.raises(PipelineError, match=r"вопрос|связь"):
        await provider.pipeline().analyze(_context([source], [_question()]))


async def test_later_conflicting_document_blocks_literal_resolution_from_earlier_document() -> None:
    literal = "Инженер готовит акт."
    earlier = _source("Описание. " * 1800 + literal)
    later = _source("Новый регламент: акт готовит бухгалтерия.", SourceKind.FILE)
    proof = replace(earlier, content=literal)

    def verify(payload):
        conflict = any("Новый регламент" in s["text"] for s in payload["sources"])
        return {
            "complete": True,
            "decisions": [
                {
                    "id": p["id"],
                    "valid": True,
                    "conflict": conflict,
                    "reason": "Новый регламент противоречит указанному исполнителю"
                    if conflict
                    else "Дословный факт относится к оформлению акта",
                }
                for p in payload["proposals"]
            ],
        }

    provider = RecordedProvider(lambda p: _analysis(p, updates=[_resolution(proof)]), verify)
    context = _context([earlier, later], [_question()])
    context.analysis_budget_chars = 20_000
    result = await provider.pipeline().analyze(context)
    assert result.question_updates == []
    assert "противоречит" in result.warnings[0]


async def test_unavailable_historical_fact_creates_linked_uncertainty_without_erasing_history() -> (
    None
):
    source = _source("После согласования акт оформляют, но исполнитель не указан.")
    old = _question(status=QuestionStatus.RESOLVED)
    old.evidence = Quote(source_id=uuid4(), quote="Инженер готовит акт.")
    provider = RecordedProvider(
        lambda p: _analysis(p, new=[_candidate(source)]),
        lambda p: {
            "complete": True,
            "decisions": [
                {
                    "id": p["id"],
                    "valid": True,
                    "same_as": "Q-1",
                    "relation": "known_fact",
                    "reason": "Старое решение совпадает",
                }
                for p in p["proposals"]
            ],
        },
    )
    context = _context([source], [old])
    result = await provider.pipeline().analyze(context)
    assert result.new_questions[0].related_code == "Q-1"
    assert "отсутствует" in result.warnings[0]
    outcome = reconcile(
        context.questions,
        result,
        [source],
        project_id=context.project_id,
        run_id=uuid4(),
        now=NOW,
        new_id=uuid4,
    )
    assert context.questions[0] == old
    assert "Q-1" in outcome.created[0].text


@pytest.mark.parametrize("change", ["source", "answer", "model", "budget", "snapshot", "coverage"])
async def test_cache_invalidates_for_source_question_model_and_output_budget(change) -> None:
    source = _source("Нет новых сведений")
    context = _context([source], [_question()])
    provider = RecordedProvider(_analysis)
    pipeline = provider.pipeline()
    await pipeline.analyze(context)
    if change == "source":
        context.evidence_sources = [replace(source, content="Появился новый факт")]
    elif change == "answer":
        context.questions[0].answer = Answer(source_id=source.id, text="Новый ответ")
    elif change == "model":
        pipeline._model = "another-recorded-model"
    elif change == "snapshot":
        context.source_snapshot_hash = "new-processing-source"
    elif change == "coverage":
        context.analysis_input_complete = False
    else:
        pipeline._json_max_tokens = 16_384
    await pipeline.analyze(context)
    assert len(provider.requests) == 2


def test_fingerprint_preserves_semantic_changes_and_ignores_di_layout() -> None:
    context = _context([_source("Регламент")])
    context.current_xml = read_bpmn("tp861_v2")
    fingerprint = snapshot_fingerprint(context)
    layout = context.current_xml.replace('x="', 'x="1', 1)
    assert snapshot_fingerprint(replace(context, current_xml=layout)) == fingerprint
    assert snapshot_fingerprint(replace(context, project_title="Другой процесс")) != fingerprint
    changed = context.current_xml.replace("Заявитель", "Экономист")
    assert snapshot_fingerprint(replace(context, current_xml=changed)) != fingerprint


def test_transport_rejects_length_even_with_valid_json_and_json_budget_is_configurable() -> None:
    pipeline = OpenAICompatiblePipeline(api_key="recorded-only", json_max_tokens=16_384)
    with patch("app.llm.openai_compatible.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            {
                "choices": [
                    {"finish_reason": "length", "message": {"content": '{"new_questions":[]}'}}
                ]
            }
        ).encode()
        with pytest.raises(OutputTruncatedError):
            pipeline._request_json("system", "prompt")
        request = json.loads(urlopen.call_args.args[0].data)
        assert request["max_tokens"] == 16_384
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            {"choices": [{"message": {"content": "legacy completed"}}]}
        ).encode()
        assert pipeline._request_text("system", "prompt") == "legacy completed"
        assert json.loads(urlopen.call_args.args[0].data)["max_tokens"] == 4096


@pytest.mark.parametrize(
    "race",
    [
        "edit",
        "delete",
        "add",
        "answer_same_status",
        "ignore",
        "processing_insert",
        "inactive_insert",
    ],
)
async def test_source_and_question_snapshot_races_do_not_apply_stale_resolutions(race) -> None:
    container = build_container(Settings(mock_delay_scale=0, seed_demo_data=False))
    project = (await container.projects.create(title="Присоединение", description=None)).project
    source = await container.sources.create_text(
        project.id,
        content="Инженер готовит акт.",
        title="Регламент",
        kind=SourceKind.TEXT,
        duration_sec=None,
    )
    question = _question(
        status=QuestionStatus.ANSWERED if race == "answer_same_status" else QuestionStatus.OPEN
    )
    question.project_id = project.id
    question.answer = Answer(source_id=source.id, text=source.content)
    await container.repos.questions.add(question)
    evidence = ContextSource(
        id=source.id,
        kind=source.kind,
        title=source.title,
        content=source.content,
        created_at=source.created_at,
    )
    provider = RecordedProvider(lambda p: _analysis(p, updates=[_resolution(evidence)]))
    container.runs._pipeline = provider.pipeline()
    entered, release = asyncio.Event(), asyncio.Event()

    async def gate(stage):
        if stage is RunStage.RECONCILING:
            entered.set()
            await release.wait()

    container.runs._pace = gate
    started = await container.runs.start(project.id, mode=RunMode.ANALYZE, created_by=None)
    await asyncio.wait_for(entered.wait(), timeout=5)
    if race == "edit":
        await container.sources.update(
            source.id,
            title=None,
            content="Акт готовит бухгалтерия.",
            active=None,
            fields={"content"},
        )
    elif race == "delete":
        await container.sources.delete(source.id)
    elif race == "add":
        await container.sources.create_text(
            project.id,
            content="Теперь акт готовит бухгалтерия.",
            title=None,
            kind=SourceKind.TEXT,
            duration_sec=None,
        )
    elif race == "ignore":
        await container.questions.ignore(question.id)
    elif race in {"processing_insert", "inactive_insert"}:
        await container.repos.sources.add(
            Source(
                id=uuid4(),
                project_id=project.id,
                kind=SourceKind.FILE,
                title="Новый документ",
                content="",
                status=SourceStatus.PROCESSING,
                active=race == "processing_insert",
                created_at=NOW,
            )
        )
    else:
        updated = deepcopy(question)
        updated.answer = Answer(source_id=source.id, text="Исполнитель пока не определён")
        updated.updated_at += timedelta(seconds=1)
        await container.repos.questions.update(updated)
    release.set()
    await container.spawner.wait_idle()
    kept = await container.repos.questions.get(question.id)
    run = await container.repos.runs.get(started.id)
    assert kept is not None
    assert kept.status is not QuestionStatus.RESOLVED
    assert run is not None
    assert run.status is RunStatus.SUCCEEDED
    assert run.summary is not None
    assert run.summary.resolved == 0
    assert any("снимку не применена" in warning for warning in run.warnings)
    assert run.analysis is not None
    assert run.analysis["audit"]["application"]["applied_question_codes"] == []
    assert await container.repos.versions.list_by_project(project.id) == []
    if race == "answer_same_status":
        assert kept.answer is not None
        assert kept.answer.text == "Исполнитель пока не определён"


async def test_memory_cas_rejects_same_status_with_newer_answer() -> None:
    container = build_container(Settings(seed_demo_data=False))
    question = _question(status=QuestionStatus.ANSWERED)
    await container.repos.questions.add(question)
    updated = replace(
        question,
        updated_at=NOW + timedelta(seconds=1),
        answer=Answer(source_id=uuid4(), text="Новая версия ответа"),
    )
    await container.repos.questions.update(updated)
    stale = replace(question, status=QuestionStatus.RESOLVED)
    assert not await container.repos.questions.apply_reconciled(
        stale, expected_status=QuestionStatus.ANSWERED, expected_updated_at=NOW
    )
    assert await container.repos.questions.get(question.id) == updated
