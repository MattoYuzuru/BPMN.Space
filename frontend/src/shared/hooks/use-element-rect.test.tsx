import { act, renderHook } from '@testing-library/react'
import { toDomRect, useElementRect } from './use-element-rect'

describe('геометрия активного якоря', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('ловит сдвиг без resize/scroll и останавливает кадры без якоря', () => {
    const frames = new Map<number, FrameRequestCallback>()
    let nextFrame = 0
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      frames.set(++nextFrame, callback)
      return nextFrame
    })
    vi.stubGlobal('cancelAnimationFrame', (id: number) => frames.delete(id))
    const element = document.createElement('div')
    let box = { x: 80, y: 100, width: 300, height: 100 }
    element.getBoundingClientRect = () => toDomRect(box)
    const { result, rerender, unmount } = renderHook(({ target }) => useElementRect(target), {
      initialProps: { target: element as Element | null },
    })
    const tick = () => {
      const pending = [...frames.values()]
      frames.clear()
      act(() => {
        for (const callback of pending) callback(performance.now())
      })
    }
    const previous = result.current
    tick()
    expect(result.current).toBe(previous)
    box = { ...box, y: 142 }
    tick()
    expect(result.current).toEqual(box)
    expect(frames.size).toBe(1)
    rerender({ target: null })
    expect(result.current).toBeNull()
    expect(frames.size).toBe(0)
    rerender({ target: element })
    expect(frames.size).toBe(1)
    unmount()
    expect(frames.size).toBe(0)
  })
})
