import { describe, expect, it } from 'vitest'
import {
  estimateCallsText,
  estimateCost,
  estimateCurrency,
  estimateDurationText,
  estimateIncomplete,
  estimateTokensText,
} from './estimate'
import type { RunEstimate } from './model'

const base: RunEstimate = {
  calls: { min: 8, max: 12 },
  complete: true,
  cost: { currency: 'USD', min_usd: 1.8, max_usd: 3.2 },
  duration: { min_sec: 45, max_sec: 125 },
  breakdown: [],
  tokens: { min: 120_000, max: 180_000 },
  notes: [],
}

describe('подписи оценки прогона', () => {
  it('отдаёт диапазон денег и валюту', () => {
    expect(estimateCost(base)).toEqual({ min: 1.8, max: 3.2 })
    expect(estimateCurrency(base)).toBe('USD')
    expect(estimateCost({ ...base, cost: null })).toBeNull()
  })

  it('пишет запросы, токены и длительность по-русски', () => {
    expect(estimateCallsText(base)).toBe('8–12\u00a0запросов')
    expect(estimateCallsText({ ...base, calls: { min: 1, max: 1 } })).toBe('1\u00a0запрос')
    expect(estimateTokensText(base)).toBe('120–180\u00a0тыс.\u00a0токенов')
    expect(estimateTokensText({ ...base, tokens: { min: 2_000_000, max: 2_000_000 } })).toBe(
      '2\u00a0млн\u00a0токенов',
    )
    expect(estimateTokensText({ ...base, tokens: { min: 950, max: 950 } })).toBe('950\u00a0токенов')
    expect(estimateDurationText(base)).toBe('45\u00a0с – 2\u00a0мин 05\u00a0с')
    expect(estimateDurationText({ ...base, duration: { min_sec: 60, max_sec: 180 } })).toBe(
      '1–3\u00a0мин',
    )
  })

  it('неполная оценка — когда нет цен или сервер сам так сказал', () => {
    expect(estimateIncomplete(base)).toBe(false)
    expect(estimateIncomplete({ ...base, complete: false })).toBe(true)
    expect(estimateIncomplete({ ...base, cost: null })).toBe(true)
  })
})
