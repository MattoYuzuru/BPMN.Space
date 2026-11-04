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

describe('сигналы волн 2–4', () => {
  it('типы объявлены и доставляются подписчику без изменений', () => {
    const listener = vi.fn()
    const unsubscribe = subscribeOnboardingSignals(listener)
    const signals = [
      { type: 'run.estimated', costMin: 1.8, costMax: 3.2, currency: 'USD', complete: true },
      { type: 'run.budget.updated', costUsd: 10 },
      { type: 'run.decisions.opened', runId: 'r1' },
      { type: 'question.technical.resolved', id: 'q1', action: 'budget' },
      { type: 'tool.credential.added', kind: 'ocr' },
      { type: 'agent.token.created', id: 't1', name: 'Claude Code' },
      { type: 'agent.command.copied' },
      { type: 'share.reviewer.created' },
      { type: 'source.player.seek', sourceId: 's1', seconds: 27 },
    ] as const
    for (const signal of signals) emitOnboardingSignal(signal)
    expect(listener.mock.calls.map(([signal]) => signal.type)).toEqual(
      signals.map((signal) => signal.type),
    )
    unsubscribe()
  })
})
