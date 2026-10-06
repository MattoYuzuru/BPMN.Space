"""Жизненный цикл вопросов (RFC §2.2) и сверка вопросов после анализа (RFC §5.1, шаг «QR»).

Переходы, которые делает аналитик:
    open → answered (ответ) · open → ignored (принять допущение) · ignored/answered → open (вернуть)
Переходы, которые делает прогон:
    open/answered/ignored → resolved (только с цитатой, найденной в источнике)
    answered → open (ответ не помог) · open/answered → obsolete (часть процесса удалена)
`resolved` и `obsolete` — конечные статусы.
"""

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from app.domain.analysis import AnalysisResult, ContextSource
from app.domain.models import Answer, Question, QuestionStatus, Quote, RunSummary

STATUS_LABELS: dict[QuestionStatus, str] = {
    QuestionStatus.OPEN: "открыт",
    QuestionStatus.ANSWERED: "отвечен",
    QuestionStatus.IGNORED: "проигнорирован",
    QuestionStatus.RESOLVED: "решён",
    QuestionStatus.OBSOLETE: "устарел",
}

_ANSWERABLE = {QuestionStatus.OPEN}
_IGNORABLE = {QuestionStatus.OPEN}
_REOPENABLE = {QuestionStatus.IGNORED, QuestionStatus.ANSWERED}
_RUN_TRANSITIONS: dict[QuestionStatus, set[QuestionStatus]] = {
    QuestionStatus.RESOLVED: {QuestionStatus.OPEN, QuestionStatus.ANSWERED, QuestionStatus.IGNORED},
    QuestionStatus.OPEN: {QuestionStatus.ANSWERED},
    QuestionStatus.OBSOLETE: {QuestionStatus.OPEN, QuestionStatus.ANSWERED},
}


class QuestionTransitionError(Exception):
    """Недопустимый переход статуса вопроса. Сообщение — для пользователя, на русском."""


def _reject(question: Question, action: str) -> QuestionTransitionError:
    label = STATUS_LABELS[question.status]
    return QuestionTransitionError(f"Вопрос {question.code} {label} — {action} нельзя")


def answer(question: Question, *, source_id: UUID, text: str, now: datetime) -> None:
    if question.status not in _ANSWERABLE:
        raise _reject(question, "ответить на него")
    question.status = QuestionStatus.ANSWERED
    question.answer = Answer(source_id=source_id, text=text)
    question.updated_at = now


def ignore(question: Question, *, now: datetime) -> None:
    if question.status not in _IGNORABLE:
        raise _reject(question, "проигнорировать его")
    question.status = QuestionStatus.IGNORED
    question.updated_at = now


def reopen(question: Question, *, now: datetime) -> UUID | None:
    """Возвращает вопрос в `open`. Для отвеченного — снимает ответ и отдаёт id источника-ответа."""
    if question.status not in _REOPENABLE:
        raise _reject(question, "вернуть его")
    answer_source_id = question.answer.source_id if question.answer else None
    question.status = QuestionStatus.OPEN
    question.answer = None
    question.updated_at = now
    return answer_source_id


def drop_answer(question: Question, *, now: datetime) -> None:
    """Источник-ответ удалён: отвеченный вопрос снова открыт, у остальных ответ просто забываем."""
    if question.status is QuestionStatus.ANSWERED:
        question.status = QuestionStatus.OPEN
    question.answer = None
    question.updated_at = now


def update_answer_text(question: Question, *, text: str, now: datetime) -> None:
    if question.answer is not None:
        question.answer = Answer(source_id=question.answer.source_id, text=text)
        question.updated_at = now


def next_code(questions: Iterable[Question]) -> str:
    numbers = [int(q.code[2:]) for q in questions if q.code[:2] == "Q-" and q.code[2:].isdigit()]
    return f"Q-{max(numbers, default=0) + 1}"


_SPACES = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Нормализация для нечёткого сравнения цитат: регистр, «ё», кавычки и пробелы."""
    text = text.casefold().replace("ё", "е")
    text = text.replace("«", '"').replace("»", '"').replace("“", '"').replace("”", '"')
    return _SPACES.sub(" ", text).strip()


def quote_in_source(quote: str, content: str) -> bool:
    """Цитата действительно есть в тексте источника — защита от выдуманных доказательств."""
    needle = normalize(quote)
    return bool(needle) and needle in normalize(content)


def find_source_with_quote(quote: str, sources: Sequence[ContextSource]) -> ContextSource | None:
    return next((s for s in sources if quote_in_source(quote, s.content)), None)


@dataclass(slots=True, kw_only=True)
class ReconcileOutcome:
    changed: list[Question] = field(default_factory=list[Question])
    created: list[Question] = field(default_factory=list[Question])
    rejected: list[str] = field(default_factory=list[str])
    summary: RunSummary = field(default_factory=RunSummary)


def reconcile(
    questions: Sequence[Question],
    analysis: AnalysisResult,
    sources: Sequence[ContextSource],
    *,
    project_id: UUID,
    run_id: UUID,
    now: datetime,
    new_id: Callable[[], UUID],
) -> ReconcileOutcome:
    """Применяет результат анализа к вопросам проекта.

    Правила (RFC §2.2): «решено» засчитывается только с цитатой, которая есть в указанном
    источнике; ссылки на несуществующие вопросы и недопустимые переходы отбрасываются
    с объяснением в `rejected`. Новые вопросы с уже существующим текстом не дублируются.
    """
    by_code = {q.code: q for q in questions}
    by_source = {s.id: s for s in sources}
    outcome = ReconcileOutcome()
    resolved_now = 0

    for update in analysis.question_updates:
        question = by_code.get(update.code)
        if question is None:
            outcome.rejected.append(f"{update.code}: такого вопроса нет")
            continue
        allowed_from = _RUN_TRANSITIONS.get(update.status, set())
        if question.status not in allowed_from:
            outcome.rejected.append(f"{update.code}: переход в «{update.status}» недопустим")
            continue
        if update.status is QuestionStatus.RESOLVED:
            evidence = update.evidence
            if evidence is None or not _quote_ok(evidence, by_source):
                outcome.rejected.append(f"{update.code}: цитата не найдена в источнике")
                continue
            question.evidence = evidence
            resolved_now += 1
        if update.status in {QuestionStatus.OPEN, QuestionStatus.OBSOLETE} and not (
            update.reason and update.reason.strip()
        ):
            outcome.rejected.append(f"{update.code}: причина изменения статуса не указана")
            continue
        if update.status is QuestionStatus.OBSOLETE and (
            update.evidence is None or not _quote_ok(update.evidence, by_source)
        ):
            outcome.rejected.append(f"{update.code}: исчезновение предмета не подтверждено цитатой")
            continue
        if update.status is QuestionStatus.OBSOLETE:
            question.evidence = update.evidence
        # Ответ остаётся частью истории даже когда его недостаточно для решения вопроса.
        question.status = update.status
        question.updated_at = now
        outcome.changed.append(question)

    all_questions = list(questions)
    for spec in analysis.new_questions:
        related = by_code.get(spec.related_code) if spec.related_code else None
        if spec.related_code and related is None:
            outcome.rejected.append(f"{spec.related_code}: исторический вопрос не найден")
            continue
        text = f"Уточнение к {related.code}: {spec.text}" if related else spec.text
        if any(
            normalize(q.text) == normalize(text)
            and q.kind is spec.kind
            and _same_context(q.element_ids, q.about, spec.element_ids, spec.about)
            for q in all_questions
        ):
            continue
        about = spec.about if spec.about and _quote_ok(spec.about, by_source) else None
        created = Question(
            id=new_id(),
            project_id=project_id,
            code=next_code(all_questions),
            kind=spec.kind,
            severity=spec.severity,
            status=QuestionStatus.OPEN,
            text=text,
            assumption=spec.assumption,
            about=about,
            element_ids=list(spec.element_ids),
            created_at=now,
            updated_at=now,
            run_id=run_id,
        )
        all_questions.append(created)
        outcome.created.append(created)

    outcome.summary = run_summary(all_questions, run_id=run_id, resolved_now=resolved_now)
    return outcome


def _quote_ok(quote: Quote, by_source: dict[UUID, ContextSource]) -> bool:
    source = by_source.get(quote.source_id)
    return source is not None and quote_in_source(quote.quote, source.content)


def _same_context(
    left_ids: list[str], left: Quote | None, right_ids: list[str], right: Quote | None
) -> bool:
    """Защитный exact fallback после семантической проверки: разные поводы не сливаем."""
    if left_ids or right_ids:
        return bool(set(left_ids) & set(right_ids))
    if left is None or right is None:
        return left is right
    return left.source_id == right.source_id and normalize(left.quote) == normalize(right.quote)


def run_summary(questions: Iterable[Question], *, run_id: UUID, resolved_now: int) -> RunSummary:
    """Итог прогона: решено в нём, осталось открытыми, новых; игнорируется и отвечено — сейчас."""
    summary = RunSummary(resolved=resolved_now)
    for q in questions:
        if q.status is QuestionStatus.OPEN:
            if q.run_id == run_id:
                summary.new += 1
            else:
                summary.open += 1
        elif q.status is QuestionStatus.IGNORED:
            summary.ignored += 1
        elif q.status is QuestionStatus.ANSWERED:
            summary.answered += 1
    return summary


def project_summary(questions: Iterable[Question], *, latest_run_id: UUID | None) -> RunSummary:
    """Текущее состояние вопросов проекта для плашки над схемой.

    `resolved` — всего решено; `new` — открытые вопросы, которые создал последний прогон;
    `open` — остальные открытые («осталось»).
    """
    summary = RunSummary()
    for q in questions:
        if q.status is QuestionStatus.RESOLVED:
            summary.resolved += 1
        elif q.status is QuestionStatus.OPEN:
            if latest_run_id is not None and q.run_id == latest_run_id:
                summary.new += 1
            else:
                summary.open += 1
        elif q.status is QuestionStatus.IGNORED:
            summary.ignored += 1
        elif q.status is QuestionStatus.ANSWERED:
            summary.answered += 1
    return summary
