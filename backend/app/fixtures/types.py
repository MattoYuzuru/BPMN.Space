"""Типы фикстур: правила mock-модели и описания демо-проектов."""

from collections.abc import Mapping
from dataclasses import dataclass, field

from app.domain.models import QuestionKind, Severity


@dataclass(frozen=True, slots=True)
class QuestionRule:
    """«Модель заметила в источниках фразу `trigger` и задала вопрос».

    Вопрос появляется при анализе, если `trigger` есть в каком-либо активном источнике
    и такого вопроса в проекте ещё нет; `trigger` становится цитатой `about`.
    """

    trigger: str
    kind: QuestionKind
    severity: Severity
    text: str
    assumption: str
    element_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResolutionRule:
    """Вопрос с текстом `question` решается цитатой `evidence` из источника, добавленного позже."""

    question: str
    evidence: str


@dataclass(frozen=True, slots=True)
class DiagramRule:
    """Записанная схема: выдаётся при сборке, если все цитаты `requires` есть в источниках.

    Из подходящих выбирается последняя в списке (самая полная версия).
    `trace` — «элемент схемы → цитата»; id источника находится по цитате при сборке.
    """

    fixture: str
    requires: tuple[str, ...]
    trace: Mapping[str, str] = field(default_factory=dict[str, str])


@dataclass(frozen=True, slots=True)
class Playbook:
    questions: tuple[QuestionRule, ...]
    resolutions: tuple[ResolutionRule, ...]
    diagrams: tuple[DiagramRule, ...]


@dataclass(frozen=True, slots=True)
class Example:
    id: str
    title: str
    description: str
    text: str  # имя файла в texts/


@dataclass(frozen=True, slots=True)
class Topic:
    """Типовой процесс энергокомпании для генерации списка проектов.

    `steps` — пары «ответственный → действие» в порядке выполнения.
    """

    key: str
    title: str
    description: str
    steps: tuple[tuple[str, str], ...]
