"""Домен онбординга: переходы статуса тура и выбор места для каждого пункта чек-листа."""

from datetime import UTC, datetime, timedelta
from itertools import product
from uuid import UUID, uuid4

import pytest

from app.domain.onboarding import (
    CLIENT_REPORTABLE,
    ChecklistItem,
    ProjectFacts,
    TargetHint,
    TargetRoute,
    TourStatus,
    TourStepKey,
    TourTransitionError,
    check_transition,
    resolve_target,
)

T0 = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
ALLOWED = {
    (TourStatus.PENDING, TourStatus.ACTIVE),
    (TourStatus.PENDING, TourStatus.DISMISSED),
    (TourStatus.ACTIVE, TourStatus.ACTIVE),
    (TourStatus.ACTIVE, TourStatus.COMPLETED),
    (TourStatus.ACTIVE, TourStatus.DISMISSED),
}


def test_catalog_matches_epic() -> None:
    assert len(ChecklistItem) == 12
    assert len(TourStepKey) == 11
    assert {ChecklistItem.SIMULATION_RUN, ChecklistItem.DIAGRAM_EXPORTED} == CLIENT_REPORTABLE


@pytest.mark.parametrize(("current", "target"), list(product(TourStatus, TourStatus)))
def test_transition_table(current: TourStatus, target: TourStatus) -> None:
    if (current, target) in ALLOWED:
        check_transition(current, target)
    else:
        with pytest.raises(TourTransitionError):
            check_transition(current, target)


@pytest.mark.parametrize("current", list(TourStatus))
def test_restart_allowed_from_any_status_but_only_to_active(current: TourStatus) -> None:
    check_transition(current, TourStatus.ACTIVE, restart=True)
    with pytest.raises(TourTransitionError):
        check_transition(current, TourStatus.COMPLETED, restart=True)


def _facts(
    minutes: int,
    *,
    owned: bool = True,
    sources: bool = False,
    ready: bool | None = None,
    diagram: bool = False,
    question: UUID | None = None,
    answered_after: bool = False,
) -> ProjectFacts:
    return ProjectFacts(
        project_id=uuid4(),
        updated_at=T0 + timedelta(minutes=minutes),
        owned=owned,
        has_sources=sources,
        has_ready_sources=sources if ready is None else ready,
        has_diagram=diagram,
        open_question_id=question,
        answered_after_diagram=answered_after,
    )


SOURCE_ITEMS = [
    ChecklistItem.TEXT_SOURCE_ADDED,
    ChecklistItem.DOCUMENT_UPLOADED,
    ChecklistItem.VOICE_ADDED,
]
DIAGRAM_ITEMS = [
    ChecklistItem.DIAGRAM_EDITED,
    ChecklistItem.SIMULATION_RUN,
    ChecklistItem.DIAGRAM_EXPORTED,
]
QUESTION_ITEMS = [ChecklistItem.QUESTION_ANSWERED, ChecklistItem.ASSUMPTION_ACCEPTED]


def test_project_created_leads_to_projects_screen_even_with_projects() -> None:
    for projects in ([], [_facts(1, diagram=True)]):
        target = resolve_target(ChecklistItem.PROJECT_CREATED, projects)
        assert (target.route, target.hint, target.project_id) == (
            TargetRoute.PROJECTS,
            TargetHint.DO_ITEM,
            None,
        )


@pytest.mark.parametrize("item", SOURCE_ITEMS)
def test_source_items_lead_to_latest_project(item: ChecklistItem) -> None:
    old, latest = _facts(1), _facts(5)
    target = resolve_target(item, [latest, old])
    assert (target.route, target.hint, target.project_id) == (
        TargetRoute.WORKSPACE,
        TargetHint.DO_ITEM,
        latest.project_id,
    )
    nothing = resolve_target(item, [])
    assert (nothing.route, nothing.hint, nothing.project_id) == (
        TargetRoute.PROJECTS,
        TargetHint.NEED_PROJECT,
        None,
    )


def test_diagram_built_prefers_buildable_project_over_newer_built_one() -> None:
    buildable, built, empty = (
        _facts(1, sources=True),
        _facts(9, sources=True, diagram=True),
        _facts(7),
    )
    target = resolve_target(ChecklistItem.DIAGRAM_BUILT, [empty, built, buildable])
    assert (target.project_id, target.hint) == (buildable.project_id, TargetHint.DO_ITEM)


def test_diagram_built_ignores_processing_sources_when_looking_for_buildable() -> None:
    processing = _facts(9, sources=True, ready=False)
    buildable = _facts(1, sources=True)
    target = resolve_target(ChecklistItem.DIAGRAM_BUILT, [processing, buildable])
    assert target.project_id == buildable.project_id


def test_diagram_built_falls_back_to_latest_project_with_sources_then_any_project() -> None:
    built = _facts(2, sources=True, diagram=True)
    processing = _facts(1, sources=True, ready=False)
    assert resolve_target(ChecklistItem.DIAGRAM_BUILT, [built, processing]).project_id in {
        built.project_id,
        processing.project_id,
    }
    empty_new, empty_old = _facts(8), _facts(3)
    target = resolve_target(ChecklistItem.DIAGRAM_BUILT, [empty_old, empty_new])
    assert (target.project_id, target.hint) == (empty_new.project_id, TargetHint.NEED_SOURCE)
    nothing = resolve_target(ChecklistItem.DIAGRAM_BUILT, [])
    assert (nothing.route, nothing.hint) == (TargetRoute.PROJECTS, TargetHint.NEED_PROJECT)


@pytest.mark.parametrize("item", QUESTION_ITEMS)
def test_question_items_lead_to_earliest_open_question(item: ChecklistItem) -> None:
    question = uuid4()
    with_question = _facts(1, sources=True, diagram=True, question=question)
    newer = _facts(9, sources=True, diagram=True)
    target = resolve_target(item, [newer, with_question])
    assert (target.project_id, target.question_id, target.hint) == (
        with_question.project_id,
        question,
        TargetHint.DO_ITEM,
    )


@pytest.mark.parametrize("item", QUESTION_ITEMS)
def test_question_items_without_questions(item: ChecklistItem) -> None:
    sources = _facts(1, sources=True)
    target = resolve_target(item, [_facts(9), sources])
    assert (target.project_id, target.question_id, target.hint) == (
        sources.project_id,
        None,
        TargetHint.NEED_QUESTIONS,
    )
    empty = _facts(2)
    assert resolve_target(item, [empty]).hint is TargetHint.NEED_SOURCE
    assert resolve_target(item, []).hint is TargetHint.NEED_PROJECT


def test_diagram_rebuilt_leads_to_project_with_answer_after_diagram() -> None:
    answered = _facts(1, sources=True, diagram=True, answered_after=True)
    newer = _facts(9, sources=True, diagram=True)
    target = resolve_target(ChecklistItem.DIAGRAM_REBUILT, [newer, answered])
    assert (target.project_id, target.hint) == (answered.project_id, TargetHint.DO_ITEM)


def test_diagram_rebuilt_without_answers_behaves_like_questions() -> None:
    question = uuid4()
    asking = _facts(1, sources=True, question=question)
    target = resolve_target(ChecklistItem.DIAGRAM_REBUILT, [_facts(9, sources=True), asking])
    assert (target.project_id, target.question_id) == (asking.project_id, question)
    only_sources = _facts(2, sources=True)
    assert (
        resolve_target(ChecklistItem.DIAGRAM_REBUILT, [only_sources]).hint
        is TargetHint.NEED_QUESTIONS
    )
    assert resolve_target(ChecklistItem.DIAGRAM_REBUILT, []).hint is TargetHint.NEED_PROJECT


@pytest.mark.parametrize("item", DIAGRAM_ITEMS)
def test_diagram_items_lead_to_latest_project_with_diagram(item: ChecklistItem) -> None:
    older = _facts(1, sources=True, diagram=True)
    newer_without = _facts(9, sources=True)
    target = resolve_target(item, [newer_without, older])
    assert (target.project_id, target.hint) == (older.project_id, TargetHint.DO_ITEM)


@pytest.mark.parametrize("item", DIAGRAM_ITEMS)
def test_diagram_items_without_diagram_point_to_previous_step(item: ChecklistItem) -> None:
    buildable = _facts(1, sources=True)
    target = resolve_target(item, [_facts(9), buildable])
    assert (target.project_id, target.hint) == (buildable.project_id, TargetHint.NEED_DIAGRAM)
    empty = _facts(2)
    target = resolve_target(item, [empty])
    assert (target.project_id, target.hint) == (empty.project_id, TargetHint.NEED_SOURCE)
    nothing = resolve_target(item, [])
    assert (nothing.route, nothing.hint) == (TargetRoute.PROJECTS, TargetHint.NEED_PROJECT)


def test_project_shared_needs_own_project() -> None:
    mine = _facts(1)
    foreign = _facts(9, owned=False, sources=True, diagram=True)
    target = resolve_target(ChecklistItem.PROJECT_SHARED, [foreign, mine])
    assert (target.project_id, target.hint) == (mine.project_id, TargetHint.DO_ITEM)
    only_foreign = resolve_target(ChecklistItem.PROJECT_SHARED, [foreign])
    assert (only_foreign.route, only_foreign.hint) == (
        TargetRoute.PROJECTS,
        TargetHint.NEED_PROJECT,
    )


def test_foreign_editable_project_counts_for_other_items() -> None:
    foreign = _facts(9, owned=False, sources=True, diagram=True)
    assert resolve_target(ChecklistItem.DIAGRAM_EDITED, [foreign]).project_id == foreign.project_id
    assert resolve_target(ChecklistItem.TEXT_SOURCE_ADDED, [foreign]).project_id == (
        foreign.project_id
    )


def test_every_item_is_resolvable() -> None:
    for item in ChecklistItem:
        assert resolve_target(item, []).route is TargetRoute.PROJECTS
