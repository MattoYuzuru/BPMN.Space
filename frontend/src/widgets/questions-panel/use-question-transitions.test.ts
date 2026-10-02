import { act, renderHook } from '@testing-library/react'
import type { Question, QuestionStatus } from '@/entities/question'
import { detectTransitions, SETTLE_MS, useQuestionTransitions } from './use-question-transitions'

const q = (id: string, status: QuestionStatus) => ({ id, status }) as Question

describe('detectTransitions', () => {
  it('первая загрузка ничего не отмечает', () => {
    expect(detectTransitions(null, [q('a', 'open')])).toEqual({ resolved: [], added: [] })
  })

  it('видит решённые и новые открытые', () => {
    const before = new Map<string, QuestionStatus>([
      ['a', 'open'],
      ['b', 'answered'],
      ['c', 'ignored'],
      ['d', 'resolved'],
    ])
    const result = detectTransitions(before, [
      q('a', 'resolved'),
      q('b', 'resolved'),
      q('c', 'ignored'),
      q('d', 'resolved'),
      q('e', 'open'),
      q('f', 'resolved'),
    ])
    expect(result).toEqual({ resolved: ['a', 'b'], added: ['e'] })
  })
})

describe('useQuestionTransitions', () => {
  it('держит решённый вопрос среди открытых, пока идёт анимация', () => {
    vi.useFakeTimers()
    const { result, rerender } = renderHook(({ list }) => useQuestionTransitions(list), {
      initialProps: { list: [q('a', 'open')] },
    })
    rerender({ list: [q('a', 'resolved')] })
    expect(result.current.settling.has('a')).toBe(true)
    act(() => vi.advanceTimersByTime(SETTLE_MS))
    expect(result.current.settling.has('a')).toBe(false)
    vi.useRealTimers()
  })
})
