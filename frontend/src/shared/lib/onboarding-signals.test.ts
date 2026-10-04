import { describe, expect, it, vi } from 'vitest'
import {
  emitOnboardingSignal,
  hasOnboardingSubscribers,
  subscribeOnboardingSignals,
} from './onboarding-signals'

describe('шина сигналов обучения', () => {
  it('без подписчиков публикация ничего не делает', () => {
    expect(hasOnboardingSubscribers()).toBe(false)
    expect(() => emitOnboardingSignal({ type: 'share.created' })).not.toThrow()
  })

  it('доставляет сигнал подписчикам и умеет отписываться', () => {
    const listener = vi.fn()
    const unsubscribe = subscribeOnboardingSignals(listener)
    emitOnboardingSignal({ type: 'source.added', kind: 'text' })
    expect(listener).toHaveBeenCalledWith({ type: 'source.added', kind: 'text' })
    unsubscribe()
    emitOnboardingSignal({ type: 'share.created' })
    expect(listener).toHaveBeenCalledTimes(1)
    expect(hasOnboardingSubscribers()).toBe(false)
  })
})
