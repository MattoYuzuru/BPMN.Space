/**
 * Оценка прогона до запуска (RFC-0005, шаг 4): подписи для диалога запуска.
 * Сам расчёт делает сервер; здесь только форматирование диапазонов и понятные статусы.
 */
import { formatDurationRange, formatNumber, formatNumberRange, pluralRu } from '@/shared/lib/format'
import type { CostRange } from '@/shared/ui'
import type { RunEstimate } from './model'

/** Диапазон денег для CostMeter; `null` — цены модели неизвестны. */
export function estimateCost(estimate: RunEstimate): CostRange | null {
  if (!estimate.cost || estimate.cost.min_usd == null || estimate.cost.max_usd == null) return null
  return { min: estimate.cost.min_usd, max: estimate.cost.max_usd }
}

export function estimateCurrency(estimate: RunEstimate): string {
  return estimate.cost?.currency || 'USD'
}

/** «8–12 запросов» — диапазон запросов к модели. */
export function estimateCallsText(estimate: RunEstimate): string {
  const range = formatNumberRange(estimate.calls.min, estimate.calls.max)
  const forms = ['запрос', 'запроса', 'запросов'] as const
  return `${range}\u00A0${pluralRu(estimate.calls.max, forms)}`
}

/** «120–180 тыс. токенов» — вход и ответ вместе. */
export function estimateTokensText(estimate: RunEstimate): string {
  const { min, max } = estimate.tokens
  const scale = max >= 1_000_000 ? 1_000_000 : max >= 1000 ? 1000 : 1
  const unit = scale === 1_000_000 ? 'млн' : scale === 1000 ? 'тыс.' : ''
  const format = (value: number) => formatNumber(Math.round(value / scale))
  const range = min === max ? format(min) : `${format(min)}–${format(max)}`
  const forms = ['токен', 'токена', 'токенов'] as const
  return `${range}${unit ? `\u00A0${unit}` : ''}\u00A0${pluralRu(max, forms)}`
}

/** «1–3 мин» — длительность прогона. */
export function estimateDurationText(estimate: RunEstimate): string {
  return formatDurationRange(estimate.duration.min_sec, estimate.duration.max_sec)
}

/** В оценке есть шаги без цен или неизвестная модель: сумма неполная. */
export function estimateIncomplete(estimate: RunEstimate): boolean {
  return !estimate.complete || estimateCost(estimate) === null
}
