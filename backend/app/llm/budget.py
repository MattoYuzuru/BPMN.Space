"""Проверка бюджета прогона перед запросом к модели (RFC-0005, шаг 5).

Общая для конвейера (`llm/pipeline.py`) и агентного цикла (`llm/agent.py`): бюджет — мягкая
остановка, а не ошибка. Считается по накопителю всего прогона, включая потраченное до
продолжения после `waiting` (журнал `llm_calls` подмешивает сервис прогонов).
"""

from app.llm.base import BudgetReachedError, current_budget, usage_totals
from app.llm.capabilities import ModelPrices
from app.llm.estimate import cost_of_usage


def check_run_budget(prices: ModelPrices | None) -> None:
    """Поднимает `BudgetReachedError`, если бюджет токенов или денег уже достигнут.

    `prices=None` — цены модели неизвестны: бюджет в деньгах в такой профиль не пускается
    (422 при запуске), поэтому проверять нечего.
    """
    budget = current_budget()
    totals = usage_totals()
    if budget is None or totals is None:
        return
    spent = totals.tokens_in + totals.tokens_out
    if budget.tokens is not None and spent >= budget.tokens:
        raise BudgetReachedError(
            f"Бюджет прогона {budget.tokens} токенов исчерпан: потрачено {spent}",
            budget=budget,
        )
    if budget.cost_usd is not None and prices is not None:
        cost = cost_of_usage(totals, prices).cost_usd
        if cost is not None and cost >= budget.cost_usd:
            raise BudgetReachedError(
                f"Бюджет прогона ${budget.cost_usd:g} исчерпан: потрачено ≈ ${cost:.2f}",
                budget=budget,
            )
