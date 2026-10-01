"""Mock LLM-пайплайн: детерминированные «ответы модели» по содержимому источников.

Анализ:
1. Отвеченный вопрос → `resolved` с цитатой из ответа; ответ «не знаю» и слишком короткий
   ответ → обратно `open` (ответ не помог).
2. Правила `ResolutionRule`: открытый или проигнорированный вопрос решается цитатой из источника,
   добавленного после вопроса.
3. Правила `QuestionRule`: новый вопрос, если фраза-триггер есть в источниках.
4. Если правил для проекта нет и вопросов ещё нет — два типовых вопроса по шагам регламента.

Структура: записанная схема (`DiagramRule`), если её цитаты есть в источниках; иначе
линейная схема по шагам, извлечённым из текста; после ручной правки — схема аналитика.
TODO(real): #5 заменить на агентов Pydantic AI (см. `base.py`); этот модуль останется
как фикстура для тестов сервисов (RFC §9.1).
"""

import re
from collections.abc import Callable, Mapping, Sequence
from uuid import UUID

from app.domain.analysis import (
    AnalysisResult,
    ContextSource,
    DiagramDraft,
    NewQuestion,
    QuestionUpdate,
    RunContext,
)
from app.domain.bpmn.linear import LinearStep, build_linear_diagram
from app.domain.models import Question, QuestionStatus, Quote, SourceKind
from app.domain.questions import find_source_with_quote, normalize, quote_in_source
from app.fixtures.generic import RESPONSIBLE_MARKER, generic_questions
from app.fixtures.types import DiagramRule, Playbook
from app.llm.base import PipelineError

_MAX_STEPS = 8
_MAX_TASK_NAME = 60
_MIN_SENTENCE = 12
_MIN_HELPFUL_ANSWER = 8
_UNHELPFUL = ("не знаю", "нет информации", "уточню позже")
_NUMBERED = re.compile(r"^\s*\d+[.)]\s+(?P<body>.+)$")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_DEFAULT_LANE = "Исполнитель"


def _trim(text: str) -> str:
    text = text.strip().rstrip(".").strip()
    if len(text) <= _MAX_TASK_NAME:
        return text
    return text[:_MAX_TASK_NAME].rsplit(" ", 1)[0] + "…"


def _capitalize(text: str) -> str:
    return text[:1].upper() + text[1:]


def _numbered_step(line: str) -> tuple[str, str | None] | None:
    match = _NUMBERED.match(line)
    if not match:
        return None
    body = match.group("body")
    task, _, rest = body.partition(RESPONSIBLE_MARKER)
    lane = _capitalize(rest.strip().rstrip(".").strip()) if rest else None
    return task.strip().rstrip("."), lane or None


def extract_steps(sources: Sequence[ContextSource]) -> list[tuple[str, str, ContextSource]]:
    """Шаги процесса (название, дорожка, источник) из текстов: нумерованные пункты
    с «Ответственный: …», иначе — предложения по порядку."""
    steps: list[tuple[str, str, ContextSource]] = []
    for source in sources:
        if source.kind is SourceKind.ANSWER:
            continue
        lane = _DEFAULT_LANE
        for line in source.content.splitlines():
            numbered = _numbered_step(line)
            if numbered:
                task, numbered_lane = numbered
                lane = numbered_lane or lane
                steps.append((task, lane, source))
        if steps:
            return steps[:_MAX_STEPS]
    for source in sources:
        if source.kind is SourceKind.ANSWER:
            continue
        for line in source.content.splitlines():
            if line.lstrip().startswith("#"):
                continue
            for sentence in _SENTENCE_END.split(line.strip()):
                if len(sentence) >= _MIN_SENTENCE:
                    steps.append((sentence.strip().rstrip("."), _DEFAULT_LANE, source))
    return steps[:_MAX_STEPS]


def _first_sentence(text: str) -> str:
    return _SENTENCE_END.split(text.strip(), maxsplit=1)[0][:200]


class MockPipeline:
    def __init__(self, *, playbook: Playbook, read_bpmn: Callable[[str], str]) -> None:
        self._playbook = playbook
        self._read_bpmn = read_bpmn

    async def analyze(self, context: RunContext) -> AnalysisResult:
        by_id = {s.id: s for s in context.sources}
        updates = [
            update
            for question in context.questions
            if (update := self._check_answer(question, by_id)) is not None
        ]
        updated = {u.code for u in updates}
        updates += [
            update
            for question in context.questions
            if question.code not in updated
            and (update := self._apply_resolutions(question, context.sources)) is not None
        ]

        known = {normalize(q.text) for q in context.questions}
        new_questions: list[NewQuestion] = []
        for rule in self._playbook.questions:
            source = find_source_with_quote(rule.trigger, context.sources)
            if source is None or normalize(rule.text) in known:
                continue
            known.add(normalize(rule.text))
            new_questions.append(
                NewQuestion(
                    kind=rule.kind,
                    severity=rule.severity,
                    text=rule.text,
                    assumption=rule.assumption,
                    about=Quote(source_id=source.id, quote=rule.trigger),
                    element_ids=list(rule.element_ids),
                )
            )
        if not context.questions and not new_questions:
            new_questions = self._generic_questions(context.sources)
        return AnalysisResult(question_updates=updates, new_questions=new_questions)

    @staticmethod
    def _check_answer(
        question: Question, sources: dict[UUID, ContextSource]
    ) -> QuestionUpdate | None:
        if question.status is not QuestionStatus.ANSWERED or question.answer is None:
            return None
        text = question.answer.text.strip()
        source = sources.get(question.answer.source_id)
        unhelpful = len(text) < _MIN_HELPFUL_ANSWER or any(
            marker in normalize(text) for marker in _UNHELPFUL
        )
        if unhelpful or source is None:
            return QuestionUpdate(
                code=question.code,
                status=QuestionStatus.OPEN,
                reason="Ответ не помог: в нём нет нужных сведений",
            )
        quote = _first_sentence(text)
        return QuestionUpdate(
            code=question.code,
            status=QuestionStatus.RESOLVED,
            evidence=Quote(source_id=source.id, quote=quote),
        )

    def _apply_resolutions(
        self, question: Question, sources: Sequence[ContextSource]
    ) -> QuestionUpdate | None:
        if question.status not in {QuestionStatus.OPEN, QuestionStatus.IGNORED}:
            return None
        for rule in self._playbook.resolutions:
            if normalize(rule.question) != normalize(question.text):
                continue
            for source in sources:
                fresh = source.created_at > question.created_at
                if fresh and quote_in_source(rule.evidence, source.content):
                    return QuestionUpdate(
                        code=question.code,
                        status=QuestionStatus.RESOLVED,
                        evidence=Quote(source_id=source.id, quote=rule.evidence),
                    )
        return None

    @staticmethod
    def _generic_questions(sources: Sequence[ContextSource]) -> list[NewQuestion]:
        steps = extract_steps(sources)
        if not steps:
            return []
        items = generic_questions([_trim(name) for name, _, _ in steps])[:2]
        result: list[NewQuestion] = []
        for item in items:
            source = find_source_with_quote(item.rule.trigger, sources)
            result.append(
                NewQuestion(
                    kind=item.rule.kind,
                    severity=item.rule.severity,
                    text=item.rule.text,
                    assumption=item.rule.assumption,
                    about=Quote(source_id=source.id, quote=item.rule.trigger) if source else None,
                    element_ids=list(item.rule.element_ids),
                )
            )
        return result

    async def structure(
        self,
        context: RunContext,
        analysis: AnalysisResult,  # noqa: ARG002 — mock не использует анализ
    ) -> DiagramDraft:
        if context.current_is_manual and context.current_xml:
            # Правки аналитика приоритетнее (RFC §5.2). TODO(real): #5 учесть их через ProcessGraph.
            return DiagramDraft(xml=context.current_xml)
        rule = self._pick_diagram(context.sources)
        if rule is not None:
            return DiagramDraft(
                xml=self._read_bpmn(rule.fixture), trace=_trace(rule.trace, context.sources)
            )
        steps = extract_steps(context.sources)
        if not steps:
            raise PipelineError("Не удалось выделить шаги процесса: опишите процесс подробнее")
        xml = build_linear_diagram(
            process_name=context.project_title,
            steps=[LinearStep(name=_trim(name), lane=lane) for name, lane, _ in steps],
        )
        trace = {
            f"Task_{i}": Quote(source_id=source.id, quote=name)
            for i, (name, _, source) in enumerate(steps, start=1)
            if quote_in_source(name, source.content)
        }
        return DiagramDraft(xml=xml, trace=trace)

    def _pick_diagram(self, sources: Sequence[ContextSource]) -> DiagramRule | None:
        matching = [
            rule
            for rule in self._playbook.diagrams
            if all(find_source_with_quote(quote, sources) for quote in rule.requires)
        ]
        return matching[-1] if matching else None


def _trace(trace: Mapping[str, str], sources: Sequence[ContextSource]) -> dict[str, Quote]:
    result: dict[str, Quote] = {}
    for element_id, quote in trace.items():
        source = find_source_with_quote(quote, sources)
        if source is not None:
            result[element_id] = Quote(source_id=source.id, quote=quote)
    return result
