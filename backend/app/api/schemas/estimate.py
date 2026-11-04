"""Схемы оценки прогона до запуска (RFC-0005, шаг 4)."""

from datetime import date
from uuid import UUID

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.api.schemas.runs import RunProfile
from app.domain.models import RunMode
from app.llm.estimate import RunEstimate as DomainRunEstimate


class IntRange(ApiModel):
    """Диапазон целых чисел: нижняя и верхняя оценка."""

    min: int = Field(ge=0)
    max: int = Field(ge=0)


class CostRange(ApiModel):
    """Диапазон стоимости; `null` — цены выбранной модели неизвестны."""

    min_usd: float | None = None
    max_usd: float | None = None
    currency: str = "USD"


class DurationRange(ApiModel):
    """Диапазон длительности прогона в секундах."""

    min_sec: int = Field(ge=0)
    max_sec: int = Field(ge=0)


class StageEstimate(ApiModel):
    """Разбивка оценки по этапам пайплайна."""

    stage: str
    label: str
    calls: IntRange
    tokens_in: IntRange
    tokens_out: IntRange
    cost: CostRange | None = None


class RunEstimate(ApiModel):
    """Оценка прогона: диапазоны, а не одно число.

    `complete=false` — на пути есть модель без цен (совместимый провайдер, mock), поэтому
    стоимость неполная. Оценка приблизительная: число запросов и длина ответов зависят от
    материалов и решений модели.
    """

    tokens: IntRange = Field(description="Всего токенов: вход и ответ")
    calls: IntRange = Field(description="Запросов к модели")
    cost: CostRange | None = Field(description="Деньги; null — цены модели неизвестны")
    duration: DurationRange
    breakdown: list[StageEstimate]
    complete: bool
    priced_on: date | None = Field(default=None, description="Дата, на которую сверены цены")
    model: str | None = None
    provider: str | None = None
    notes: list[str] = Field(default_factory=list)

    @classmethod
    def of(
        cls,
        estimate: DomainRunEstimate,
        *,
        model: str | None,
        provider: str | None,
    ) -> "RunEstimate":
        return cls(
            tokens=IntRange(min=estimate.tokens.min, max=estimate.tokens.max),
            calls=IntRange(min=estimate.calls.min, max=estimate.calls.max),
            cost=CostRange(
                min_usd=estimate.cost.min_usd,
                max_usd=estimate.cost.max_usd,
                currency=estimate.cost.currency,
            )
            if estimate.cost is not None
            else None,
            duration=DurationRange(
                min_sec=estimate.duration_sec.min, max_sec=estimate.duration_sec.max
            ),
            breakdown=[
                StageEstimate(
                    stage=item.stage,
                    label=item.label,
                    calls=IntRange(min=item.calls.min, max=item.calls.max),
                    tokens_in=IntRange(min=item.tokens_in.min, max=item.tokens_in.max),
                    tokens_out=IntRange(min=item.tokens_out.min, max=item.tokens_out.max),
                    cost=CostRange(
                        min_usd=item.cost.min_usd,
                        max_usd=item.cost.max_usd,
                        currency=item.cost.currency,
                    )
                    if item.cost is not None
                    else None,
                )
                for item in estimate.breakdown
            ],
            complete=estimate.complete,
            priced_on=estimate.priced_on,
            model=model,
            provider=provider,
            notes=list(estimate.notes),
        )


class RunEstimateRequest(ApiModel):
    """Что оценивать: режим и тот же профиль, что будет у запуска."""

    mode: RunMode = Field(default=RunMode.BUILD, description="`analyze` или `build`")
    credential_id: UUID | None = Field(
        default=None,
        description="Свой ключ модели; не задан — ключ по умолчанию, затем модель сервера",
    )
    model: str | None = Field(
        default=None, max_length=128, description="Модель; требует `credential_id`"
    )
    profile: RunProfile | None = Field(
        default=None, description="Профиль прогона: effort и смысловая сверка"
    )
