"""Примеры для `GET /examples` и `POST /projects/from-example`.

Копии входа и выхода лежат в корневом `examples/`.
"""

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
        id="repair-outage",
        title="Вывод оборудования в ремонт",
        description=(
            "Диспетчерская заявка собственника, решение диспетчерского центра, переключения, "
            "продление заявки и ввод оборудования в работу."
        ),
        text="repair_outage.md",
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
)
