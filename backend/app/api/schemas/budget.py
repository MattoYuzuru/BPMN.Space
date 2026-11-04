"""Схема бюджета прогона (RFC-0005, шаг 5): мягкая остановка по токенам и/или деньгам."""

from pydantic import Field, model_validator

from app.api.schemas.common import ApiModel
from app.llm.capabilities import Budget as DomainBudget


class RunBudget(ApiModel):
    """Бюджет одного прогона: хотя бы одна граница должна быть задана.

    Достигнутый бюджет не роняет прогон: он переходит в `waiting` с блокирующим техническим
    вопросом `budget_reached`, и после решения пользователя продолжается.
    """

    tokens: int | None = Field(
        default=None,
        ge=1,
        description="Лимит суммы входных и выходных токенов прогона",
    )
    cost_usd: float | None = Field(
        default=None,
        gt=0,
        description="Лимит стоимости в долларах по ценам справочника на момент вызова",
    )

    @model_validator(mode="after")
    def _at_least_one(self) -> "RunBudget":
        if self.tokens is None and self.cost_usd is None:
            raise ValueError("Укажите бюджет в токенах и/или стоимость в долларах")
        return self

    def to_domain(self) -> DomainBudget:
        return DomainBudget(tokens=self.tokens, cost_usd=self.cost_usd)

    @classmethod
    def of(cls, budget: DomainBudget | None) -> "RunBudget | None":
        if budget is None:
            return None
        return cls(tokens=budget.tokens, cost_usd=budget.cost_usd)
