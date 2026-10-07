"""Mock LLM-пайплайн: детерминированные «ответы модели» по содержимому источников.

Анализ:
1. Отвеченный вопрос → `resolved` с цитатой из ответа; ответ «не знаю» и слишком короткий
   ответ → обратно `open` (ответ не помог).
2. Правила `ResolutionRule`: открытый или проигнорированный вопрос решается цитатой из источника,
   добавленного после вопроса.
3. Правила `QuestionRule`: новый вопрос, если фраза-триггер есть в источниках.
4. Если правил для проекта нет и вопросов ещё нет — два типовых вопроса по шагам регламента.

Управляемые режимы для e2e и тестов — маркеры в тексте любого источника (только mock):
`[[mock:fail-early]]` — анализ падает на этапе `extracting` (вопросов нет);
`[[mock:fail-structuring]]` — сборка падает на `structuring` после сверки (вопросы уже созданы);
`[[mock:no-questions]]` — новых вопросов нет, схема строится.

Структура: записанная схема (`DiagramRule`), если её цитаты есть в источниках; иначе
линейная схема по шагам, извлечённым из текста; после ручной правки — схема аналитика.
Рабочий путь — `openai_compatible.py`; этот модуль остаётся фикстурой для
тестов сервисов и демо без ключа (RFC §9.1).
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
from app.domain.bpmn.importer import import_graph
from app.domain.bpmn.linear import LinearStep, build_linear_diagram
from app.domain.bpmn.manual import ManualPolicy
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

MARKER_FAIL_EARLY = "[[mock:fail-early]]"
MARKER_FAIL_STRUCTURING = "[[mock:fail-structuring]]"
MARKER_NO_QUESTIONS = "[[mock:no-questions]]"


_MARKER = re.compile(r"\[\[mock:[a-z-]+\]\]")


def _has_marker(marker: str, sources: Sequence[ContextSource]) -> bool:
    return any(marker in source.content for source in sources)


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


def _lines(source: ContextSource) -> list[str]:
    """Строки источника без маркеров управляемого режима: они не часть процесса."""
    return _MARKER.sub("", source.content).splitlines()


def extract_steps(sources: Sequence[ContextSource]) -> list[tuple[str, str, ContextSource]]:
    """Шаги процесса (название, дорожка, источник) из текстов: нумерованные пункты
    с «Ответственный: …», иначе — предложения по порядку."""
    steps: list[tuple[str, str, ContextSource]] = []
    for source in sources:
        if source.kind is SourceKind.ANSWER:
            continue
        lane = _DEFAULT_LANE
        for line in _lines(source):
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
        for line in _lines(source):
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

    @property
    def model_name(self) -> str:
        return "recorded-fixtures"

    async def analyze(self, context: RunContext) -> AnalysisResult:
        if _has_marker(MARKER_FAIL_EARLY, context.sources):
            raise PipelineError("Модель не ответила (режим mock: fail-early)")
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
        if _has_marker(MARKER_NO_QUESTIONS, context.sources):
            new_questions = []
        elif (
            not context.questions
            and not new_questions
            and not (
                (diagram := self._pick_diagram(context.sources)) and diagram.questions_complete
            )
        ):
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
        if _has_marker(MARKER_FAIL_STRUCTURING, context.sources):
            raise PipelineError("Не удалось построить схему (режим mock: fail-structuring)")
        if (
            (context.current_is_manual or context.manual_overrides)
            and context.current_xml
            and not context.replace_manual
        ):
            # Демо сохраняет исходный XML и ту же manual-policy для следующих сборок.
            sources = {source.id: source for source in context.evidence_sources or context.sources}
            trace = {
                element_id: quote
                for element_id, quote in context.current_trace.items()
                if quote.source_id in sources
                and quote_in_source(quote.quote, sources[quote.source_id].content)
            }
            policy = context.manual_overrides
            if context.current_is_manual:
                try:
                    graph = import_graph(context.current_xml)
                    base = (
                        import_graph(context.base_generated_xml)
                        if context.base_generated_xml
                        else None
                    )
                    policy = ManualPolicy.compare(graph, base, policy).dump()
                except ValueError:
                    policy = {"opaque_manual": True}
            return DiagramDraft(xml=context.current_xml, trace=trace, manual_overrides=policy)
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
