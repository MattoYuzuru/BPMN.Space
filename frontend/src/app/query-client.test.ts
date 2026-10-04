import { afterEach, describe, expect, it } from 'vitest'
import { onboardingKeys } from '@/entities/onboarding'
import { ApiError } from '@/shared/api/client'
import { queryClient, shouldRetry } from './query-client'

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

describe('общий клиент запросов: свежесть чек-листа', () => {
  const key = onboardingKeys.user('u1')

  afterEach(() => queryClient.clear())

  it('после любой успешной мутации состояние онбординга перечитывается', async () => {
    queryClient.setQueryData(key, { enabled: true })
    expect(queryClient.getQueryState(key)?.isInvalidated).toBe(false)

    await queryClient
      .getMutationCache()
      .build(queryClient, { mutationFn: async () => 'ok' })
      .execute(undefined)

    expect(queryClient.getQueryState(key)?.isInvalidated).toBe(true)
  })

  it('неудачная мутация состояние не трогает', async () => {
    queryClient.setQueryData(key, { enabled: true })
    await queryClient
      .getMutationCache()
      .build(queryClient, {
        mutationFn: async () => {
          throw new Error('нет')
        },
      })
      .execute(undefined)
      .catch(() => undefined)
    expect(queryClient.getQueryState(key)?.isInvalidated).toBe(false)
  })
})
