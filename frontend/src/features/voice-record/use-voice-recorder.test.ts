import { renderHook, waitFor } from '@testing-library/react'
import { act } from 'react'
import { levelFromSamples, pickMimeType, useVoiceRecorder } from './use-voice-recorder'

describe('запись голоса', () => {
  it('тишина — ноль, громкий сигнал — до единицы', () => {
    expect(levelFromSamples(new Uint8Array(64).fill(128))).toBe(0)
    expect(levelFromSamples(new Uint8Array(64).fill(255))).toBe(1)
    const speech = Uint8Array.from({ length: 64 }, (_, i) => (i % 2 ? 148 : 108))
    const level = levelFromSamples(speech)
    expect(level).toBeGreaterThan(0.3)
    expect(level).toBeLessThan(1)
    expect(levelFromSamples([])).toBe(0)
  })

  it('выбирает opus в доступном контейнере', () => {
    expect(pickMimeType(() => true)).toBe('audio/webm;codecs=opus')
    expect(pickMimeType((type) => type.startsWith('audio/ogg'))).toBe('audio/ogg;codecs=opus')
    expect(pickMimeType(() => false)).toBeUndefined()
  })

  it('отказ в доступе — понятное состояние, а не исключение', async () => {
    vi.stubGlobal('MediaRecorder', class {})
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getUserMedia: () => Promise.reject(new DOMException('нет', 'NotAllowedError')),
      },
    })
    const { result } = renderHook(() => useVoiceRecorder())
    await act(() => result.current.start())
    await waitFor(() =>
      expect(result.current.state).toEqual({ status: 'blocked', reason: 'denied' }),
    )
    vi.unstubAllGlobals()
  })

  it('без MediaRecorder сообщает, что браузер не умеет записывать', async () => {
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: undefined })
    const { result } = renderHook(() => useVoiceRecorder())
    await act(() => result.current.start())
    expect(result.current.state).toEqual({ status: 'blocked', reason: 'unsupported' })
  })
})
