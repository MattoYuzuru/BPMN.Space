"""Примеры для `GET /examples` и `POST /projects/from-example`.

Копии входа и выхода лежат в корневом `examples/`.
"""

from app.fixtures.complex_examples import COMPLEX_EXAMPLES
from app.fixtures.types import Example

EXAMPLES: tuple[Example, ...] = (
    Example(
        id="tp861",
        title="Технологическое присоединение (ПП № 861)",
        description=(
            "Заявка, проверка комплектности с доработкой, развилка по мощности, параллельные "
            "мероприятия по техническим условиям, акт и договор энергоснабжения."
        ),
        text="tp861_regulation.md",
    ),
    Example(
        id="work-permit",
        title="Работы по наряду-допуску",
        description=(
            "Выдача наряда, параллельная подготовка рабочего места и бригады, "
            "целевой инструктаж, закрытие наряда."
        ),
        text="work_permit.md",
    ),
    *(
        Example(
            id=example.key,
            title=example.title,
            description=example.description,
            text=f"{example.fixture}.md",
        )
        for example in COMPLEX_EXAMPLES
    ),
)
