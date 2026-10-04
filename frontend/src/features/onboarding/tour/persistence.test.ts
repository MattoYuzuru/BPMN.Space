import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { persistQuietly } from './persistence'

beforeEach(() => {
  vi.useFakeTimers()
})
afterEach(() => {
  vi.useRealTimers()
})

describe('persistQuietly', () => {
  it('вызывает запись один раз при успехе', async () => {
    const task = vi.fn().mockResolvedValue(undefined)
    persistQuietly(task)
    await vi.advanceTimersByTimeAsync(5000)
    expect(task).toHaveBeenCalledTimes(1)
  })

  it('повторяет один раз при ошибке сети и больше не пытается', async () => {
    const task = vi.fn().mockRejectedValue(new Error('сеть'))
    persistQuietly(task)
    await vi.advanceTimersByTimeAsync(100)
    expect(task).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(2000)
    expect(task).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(10_000)
    expect(task).toHaveBeenCalledTimes(2)
  })

  it('не падает, если запись бросает синхронно', async () => {
    const task = vi.fn(() => {
      throw new Error('сразу')
    })
    expect(() => persistQuietly(task)).not.toThrow()
    await vi.advanceTimersByTimeAsync(2000)
    expect(task).toHaveBeenCalledTimes(2)
  })
})
