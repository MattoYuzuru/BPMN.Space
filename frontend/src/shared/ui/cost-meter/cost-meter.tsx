import type { ReactNode } from 'react'
import { cn } from '@/shared/lib/cn'
import { formatMoney, formatMoneyRange } from '@/shared/lib/format'
import { Icon } from '../icon'

/** Диапазон стоимости прогона: оценка до запуска всегда приблизительная. */
export interface CostRange {
  min: number
  max: number
}

export interface CostMeterProps {
  /** Оценка до запуска. */
  estimate?: CostRange | null
  /** Уже потрачено по журналу вызовов. */
  spent?: number | null
  /** Бюджет прогона в той же валюте; без него показываем только сумму. */
  budget?: number | null
  currency?: string
  /** В оценке есть шаги без известных цен — сумма неполная. */
  incomplete?: boolean
  /** Подпись слева: «Стоимость прогона», «Бюджет». Без неё — только сумма. */
  label?: ReactNode
  size?: 'sm' | 'md'
  className?: string
}

const clamp = (value: number) => Math.min(100, Math.max(0, value))
/** Процент дорожки без хвоста плавающей точки. */
const percent = (value: number) => `${Math.round(clamp(value) * 100) / 100}%`

/**
 * Стоимость прогона: диапазон оценки и/или потраченное против бюджета (RFC-0005).
 * Тон всегда смысловой: превышение бюджета — Сурик, неполная оценка — Янтарь.
 */
export function CostMeter({
  estimate,
  spent,
  budget,
  currency = 'USD',
  incomplete = false,
  label,
  size = 'md',
  className,
}: CostMeterProps) {
  const spentValue = spent ?? null
  const estimateValue = estimate ?? null
  // Нулевой и отрицательный бюджет — «бюджет не задан»: делить на него нельзя.
  const budgetValue = budget !== null && budget !== undefined && budget > 0 ? budget : null
  const spentOver = budgetValue !== null && spentValue !== null && spentValue > budgetValue
  const estimateOver =
    budgetValue !== null && estimateValue !== null && estimateValue.max > budgetValue
  const main =
    spentValue !== null
      ? formatMoney(spentValue, currency)
      : estimateValue
        ? `≈ ${formatMoneyRange(estimateValue.min, estimateValue.max, currency)}`
        : null
  const estimateBand =
    budgetValue !== null && estimateValue !== null
      ? {
          left: clamp((estimateValue.min / budgetValue) * 100),
          width: clamp(((estimateValue.max - estimateValue.min) / budgetValue) * 100),
        }
      : null
  const spentWidth =
    budgetValue !== null && spentValue !== null ? clamp((spentValue / budgetValue) * 100) : 0
  const remaining =
    budgetValue !== null && spentValue !== null && !spentOver
      ? Math.max(budgetValue - spentValue, 0)
      : null
  const hasNotes = spentOver || estimateOver || incomplete || remaining !== null

  return (
    // biome-ignore lint/a11y/useSemanticElements: смысловая группа без формы — fieldset тут не подходит
    <div
      role="group"
      aria-label={typeof label === 'string' ? label : 'Стоимость прогона'}
      className={cn('flex w-full flex-col gap-1.5', className)}
    >
      {(label || main) && (
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          {label && (
            <span className={cn('text-fg-muted', size === 'sm' ? 'type-caption' : 'type-label')}>
              {label}
            </span>
          )}
          {main && (
            <span
              className={cn(
                'text-fg',
                spentOver && 'text-danger-fg',
                estimateOver && !spentOver && 'text-amber-fg',
                size === 'sm' ? 'type-ui' : 'type-ui font-medium',
              )}
              data-numeric
            >
              {main}
              {budgetValue !== null && (
                <span className="text-fg-subtle"> из {formatMoney(budgetValue, currency)}</span>
              )}
            </span>
          )}
        </div>
      )}

      {budgetValue !== null && (spentValue !== null || estimateValue !== null) && (
        <div
          aria-hidden="true"
          data-testid="cost-meter-bar"
          className={cn(
            'relative w-full overflow-hidden rounded-full bg-pressed',
            size === 'sm' ? 'h-1' : 'h-1.5',
          )}
        >
          {estimateBand && (
            <span
              data-part="estimate"
              className="absolute inset-y-0 rounded-full bg-accent/30"
              style={{ left: percent(estimateBand.left), width: percent(estimateBand.width) }}
            />
          )}
          {spentValue !== null && (
            <span
              data-part="spent"
              className={cn(
                'absolute inset-y-0 left-0 rounded-full',
                spentOver ? 'bg-danger' : 'bg-accent',
              )}
              style={{ width: percent(spentWidth) }}
            />
          )}
        </div>
      )}

      {hasNotes && (
        <div className="flex min-h-4 flex-col gap-0.5">
          {spentOver && (
            <p className="flex items-center gap-1 type-caption text-danger-fg">
              <Icon name="alert-triangle" size={14} />
              Выше бюджета
            </p>
          )}
          {estimateOver && (
            <p className="flex items-center gap-1 type-caption text-amber-fg">
              <Icon name="alert-triangle" size={14} />
              Может превысить бюджет
            </p>
          )}
          {incomplete && (
            <p className="flex items-center gap-1 type-caption text-amber-fg">
              <Icon name="alert-triangle" size={14} />
              Неполная оценка: не у всех шагов известны цены
            </p>
          )}
          {remaining !== null && (
            <p className="type-caption text-fg-subtle" data-numeric>
              Осталось {formatMoney(remaining, currency)}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
