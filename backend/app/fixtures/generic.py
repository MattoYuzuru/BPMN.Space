"""Шаблоны для процессов без записанной схемы: текст регламента и типовые вопросы.

Используются сидом (36 типовых проектов) и mock-моделью для проектов пользователя,
для которых в `playbook.py` нет правил.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.models import QuestionKind, Severity
from app.fixtures.types import QuestionRule, Topic

RESPONSIBLE_MARKER = "Ответственный:"


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:]


def regulation_text(topic: Topic) -> str:
    """Регламент в виде нумерованного порядка действий — его разбирает mock-модель."""
    lines = [topic.title, "", topic.description, "", "Порядок действий:"]
    lines += [
        f"{i}. {task}. {RESPONSIBLE_MARKER} {_lower_first(role)}."
        for i, (role, task) in enumerate(topic.steps, start=1)
    ]
    return "\n".join(lines)


def meeting_note(topic: Topic) -> str:
    task = topic.steps[len(topic.steps) // 2][1]
    return (
        "Заметка после разговора с исполнителями. "
        f"На практике шаг «{task}» часто затягивается, срок в регламенте не указан."
    )


@dataclass(frozen=True, slots=True)
class GenericQuestion:
    rule: QuestionRule
    answer: str


def generic_questions(task_names: Sequence[str]) -> list[GenericQuestion]:
    """До четырёх типовых вопросов по шагам; `element_ids` — id задач линейной схемы."""
    if not task_names:
        return []
    last = len(task_names)
    middle = max(1, last // 2)
    items = [
        GenericQuestion(
            rule=QuestionRule(
                trigger=task_names[0],
                kind=QuestionKind.MISSING_ACTOR,
                severity=Severity.MAJOR,
                text=f"Кто подменяет ответственного за шаг «{task_names[0]}»?",
                assumption="Шаг выполняет непосредственный руководитель ответственного",
                element_ids=("Task_1",),
            ),
            answer=(
                "Ответственного подменяет его непосредственный руководитель, "
                "это закреплено в должностной инструкции."
            ),
        ),
        GenericQuestion(
            rule=QuestionRule(
                trigger=task_names[-1],
                kind=QuestionKind.MISSING_OUTCOME,
                severity=Severity.MAJOR,
                text=f"Что происходит, если шаг «{task_names[-1]}» завершился отказом?",
                assumption="Процесс завершается, инициатор получает уведомление о причине",
                element_ids=(f"Task_{last}",),
            ),
            answer="При отказе процесс завершается, инициатору направляется уведомление.",
        ),
    ]
    if last >= 2:  # noqa: PLR2004 — для вопроса о сроке и порядке нужны два разных шага
        items.append(
            GenericQuestion(
                rule=QuestionRule(
                    trigger=task_names[middle - 1],
                    kind=QuestionKind.AMBIGUOUS_CONDITION,
                    severity=Severity.MINOR,
                    text=f"В какой срок нужно выполнить шаг «{task_names[middle - 1]}»?",
                    assumption="Срок — 5 рабочих дней",
                    element_ids=(f"Task_{middle}",),
                ),
                answer="Срок — 5 рабочих дней с момента поступления документов.",
            )
        )
        items.append(
            GenericQuestion(
                rule=QuestionRule(
                    trigger=task_names[middle],
                    kind=QuestionKind.UNCLEAR_ORDER,
                    severity=Severity.MINOR,
                    text=(
                        f"Шаги «{task_names[middle - 1]}» и «{task_names[middle]}» идут "
                        "строго друг за другом или могут выполняться параллельно?"
                    ),
                    assumption="Строго последовательно, как в регламенте",
                    element_ids=(f"Task_{middle}", f"Task_{middle + 1}"),
                ),
                answer="Строго последовательно: следующий шаг начинается после предыдущего.",
            )
        )
    return items
