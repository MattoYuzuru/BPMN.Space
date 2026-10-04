import { describe, expect, it } from 'vitest'
import { ApiError } from '@/shared/api/client'
import { shouldRetry } from './query-client'

describe('shouldRetry', () => {
  it('не повторяет, когда повтор бессмыслен', () => {
    for (const status of [401, 403, 429]) {
      expect(shouldRetry(0, new ApiError(status, 'x'))).toBe(false)
    }
  })

  it('временные сбои повторяет дважды', () => {
    expect(shouldRetry(0, new ApiError(500, 'x'))).toBe(true)
    expect(shouldRetry(1, new TypeError('network'))).toBe(true)
    expect(shouldRetry(2, new TypeError('network'))).toBe(false)
  })
})
