import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { typingTimes, useTypewriter } from './use-typewriter'

beforeEach(() => {
  vi.useFakeTimers()
})
afterEach(() => {
  vi.useRealTimers()
})

describe('typingTimes', () => {
  it('45 символов в секунду без пауз', () => {
    const times = typingTimes('abcd', 45, false)
    expect(times).toHaveLength(4)
    expect(times[3]).toBeCloseTo((4 * 1000) / 45, 5)
  })

  it('паузы на знаках препинания: точка 120 мс, запятая 60 мс', () => {
    const plain = typingTimes('ab', 45, true)
    const withComma = typingTimes('a,b', 45, true)
    const withDot = typingTimes('a.b', 45, true)
    expect((withComma[2] as number) - (plain[1] as number)).toBeCloseTo(1000 / 45 + 60, 5)
    expect((withDot[2] as number) - (plain[1] as number)).toBeCloseTo(1000 / 45 + 120, 5)
  })

  it('страница в 160 символов печатается не дольше 3,5 с', () => {
    const page = `${'слово '.repeat(25)}конец, да.`
    const times = typingTimes(page.slice(0, 160), 45, true, 3500)
    expect(times.at(-1)).toBeLessThanOrEqual(3500)
  })
})

describe('useTypewriter', () => {
  it('печатает текст по мере времени и сообщает о завершении', () => {
    const onComplete = vi.fn()
    const { result } = renderHook(() => useTypewriter({ text: 'Привет', onComplete }))
    expect(result.current.text).toBe('')
    act(() => {
      vi.advanceTimersByTime(100)
    })
    expect(result.current.text.length).toBeGreaterThan(0)
    expect(result.current.text.length).toBeLessThan(6)
    expect(result.current.done).toBe(false)
    act(() => {
      vi.advanceTimersByTime(1000)
    })
    expect(result.current.text).toBe('Привет')
    expect(result.current.done).toBe(true)
    expect(onComplete).toHaveBeenCalledTimes(1)
  })

  it('finish допечатывает мгновенно', () => {
    const { result } = renderHook(() => useTypewriter({ text: 'Длинный текст страницы.' }))
    act(() => {
      vi.advanceTimersByTime(60)
    })
    expect(result.current.done).toBe(false)
    act(() => result.current.finish())
    expect(result.current.text).toBe('Длинный текст страницы.')
    expect(result.current.done).toBe(true)
  })

  it('instant показывает текст целиком сразу', () => {
    const { result } = renderHook(() => useTypewriter({ text: 'Уже читали', instant: true }))
    expect(result.current.text).toBe('Уже читали')
    expect(result.current.done).toBe(true)
  })

  it('active=false не печатает; запуск позже печатает в поле со скоростью ~120 симв/с', () => {
    const { result, rerender } = renderHook(
      ({ active }) =>
        useTypewriter({ text: 'a'.repeat(120), cps: 120, punctuationPause: false, active }),
      { initialProps: { active: false } },
    )
    act(() => {
      vi.advanceTimersByTime(500)
    })
    expect(result.current.text).toBe('')
    rerender({ active: true })
    act(() => {
      vi.advanceTimersByTime(530)
    })
    expect(result.current.done).toBe(false)
    act(() => {
      vi.advanceTimersByTime(600)
    })
    expect(result.current.done).toBe(true)
  })

  it('смена текста запускает печать заново', () => {
    const { result, rerender } = renderHook(({ text }) => useTypewriter({ text }), {
      initialProps: { text: 'Первый' },
    })
    act(() => {
      vi.advanceTimersByTime(1000)
    })
    expect(result.current.done).toBe(true)
    rerender({ text: 'Второй текст' })
    expect(result.current.text).toBe('')
    expect(result.current.done).toBe(false)
  })
})
