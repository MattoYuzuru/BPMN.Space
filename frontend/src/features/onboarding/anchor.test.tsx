import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAnchorElement } from './anchor'

function addAnchor(name: string): HTMLButtonElement {
  const element = document.createElement('button')
  element.setAttribute('data-tour', name)
  document.body.append(element)
  return element
}

beforeEach(() => {
  vi.useFakeTimers()
})
afterEach(() => {
  vi.useRealTimers()
  document.body.innerHTML = ''
})

describe('useAnchorElement', () => {
  it('находит уже существующий якорь сразу', () => {
    const element = addAnchor('now')
    const { result } = renderHook(() => useAnchorElement('[data-tour="now"]'))
    expect(result.current.element).toBe(element)
    expect(result.current.timedOut).toBe(false)
  })

  it('ждёт появления якоря через MutationObserver', async () => {
    const { result } = renderHook(() => useAnchorElement('[data-tour="later"]'))
    expect(result.current.element).toBeNull()
    let element: HTMLElement | undefined
    await act(async () => {
      vi.advanceTimersByTime(1000)
      element = addAnchor('later')
      await Promise.resolve()
      vi.advanceTimersByTime(300)
    })
    expect(result.current.element).toBe(element)
    expect(result.current.timedOut).toBe(false)
  })

  it('не нашёл за 5 с — timedOut', () => {
    const { result } = renderHook(() => useAnchorElement('[data-tour="missing"]'))
    act(() => {
      vi.advanceTimersByTime(4900)
    })
    expect(result.current.timedOut).toBe(false)
    act(() => {
      vi.advanceTimersByTime(200)
    })
    expect(result.current).toEqual({ element: null, timedOut: true })
  })

  it('таймаут настраивается', () => {
    const { result } = renderHook(() =>
      useAnchorElement('[data-tour="missing"]', { timeoutMs: 1000 }),
    )
    act(() => {
      vi.advanceTimersByTime(1100)
    })
    expect(result.current.timedOut).toBe(true)
  })

  it('исчезновение найденного якоря запускает ожидание заново', async () => {
    const element = addAnchor('gone')
    const { result } = renderHook(() => useAnchorElement('[data-tour="gone"]'))
    expect(result.current.element).toBe(element)
    await act(async () => {
      element.remove()
      await Promise.resolve()
    })
    expect(result.current.element).toBeNull()
    expect(result.current.timedOut).toBe(false)
    act(() => {
      vi.advanceTimersByTime(5100)
    })
    expect(result.current.timedOut).toBe(true)
  })

  it('без селектора и при enabled=false ничего не наблюдает', () => {
    const observe = vi.spyOn(MutationObserver.prototype, 'observe')
    renderHook(() => useAnchorElement(null))
    renderHook(() => useAnchorElement('[data-tour="x"]', { enabled: false }))
    expect(observe).not.toHaveBeenCalled()
    observe.mockRestore()
  })
})
