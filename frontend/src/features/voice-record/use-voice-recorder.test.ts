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

  describe('микрофон освобождается, если запись отменили до выдачи разрешения', () => {
    function pendingMicrophone() {
      const track = { stop: vi.fn() }
      const stream = { getTracks: () => [track] } as unknown as MediaStream
      const settlers: {
        resolve: (value: MediaStream) => void
        reject: (error: unknown) => void
      }[] = []
      const getUserMedia = vi.fn(
        () =>
          new Promise<MediaStream>((resolve, reject) => {
            settlers.push({ resolve, reject })
          }),
      )
      vi.stubGlobal('MediaRecorder', class {})
      Object.defineProperty(navigator, 'mediaDevices', {
        configurable: true,
        value: { getUserMedia },
      })
      return {
        track,
        getUserMedia,
        grant: (index = 0) => settlers[index]?.resolve(stream),
        deny: (index: number) =>
          settlers[index]?.reject(new DOMException('нет', 'NotAllowedError')),
      }
    }

    afterEach(() => vi.unstubAllGlobals())

    it('окно закрыли, пока браузер спрашивал разрешение', async () => {
      const mic = pendingMicrophone()
      const { result, unmount } = renderHook(() => useVoiceRecorder())
      let started: Promise<void> = Promise.resolve()
      act(() => {
        started = result.current.start()
      })
      unmount()

      await act(async () => {
        mic.grant()
        await started
      })

      expect(mic.track.stop).toHaveBeenCalledOnce()
    })

    it('отмена во время запроса не оставляет дорожки включёнными', async () => {
      const mic = pendingMicrophone()
      const { result } = renderHook(() => useVoiceRecorder())
      let started: Promise<void> = Promise.resolve()
      act(() => {
        started = result.current.start()
      })
      act(() => result.current.cancel())

      await act(async () => {
        mic.grant()
        await started
      })

      expect(mic.track.stop).toHaveBeenCalledOnce()
      expect(result.current.state).toEqual({ status: 'idle' })
    })

    it('двойной запуск (StrictMode): устаревший запрос освобождает свой поток', async () => {
      const mic = pendingMicrophone()
      const { result, unmount } = renderHook(() => useVoiceRecorder())
      let first: Promise<void> = Promise.resolve()
      act(() => {
        first = result.current.start()
      })
      unmount()
      const { result: remounted } = renderHook(() => useVoiceRecorder())
      let second: Promise<void> = Promise.resolve()
      act(() => {
        second = remounted.current.start()
      })

      await act(async () => {
        mic.grant(0)
        mic.deny(1)
        await first
        await second
      })

      expect(mic.track.stop).toHaveBeenCalledOnce()
      expect(remounted.current.state).toEqual({ status: 'blocked', reason: 'denied' })
    })
  })
})

it('поздняя остановка отменённой записи не закрывает новую запись', async () => {
  const tracks: { stop: ReturnType<typeof vi.fn> }[] = []
  const recorders: FakeRecorder[] = []
  class FakeRecorder {
    static isTypeSupported() {
      return true
    }
    state = 'inactive'
    mimeType = 'audio/webm'
    onstop: (() => void) | null = null
    ondataavailable: ((event: { data: Blob }) => void) | null = null
    constructor() {
      recorders.push(this)
    }
    start() {
      this.state = 'recording'
    }
    stop() {
      this.state = 'inactive'
    }
  }
  class FakeAudioContext {
    close = vi.fn(async () => undefined)
    createAnalyser() {
      return { fftSize: 1024, smoothingTimeConstant: 0.6, getByteTimeDomainData: vi.fn() }
    }
    createMediaStreamSource() {
      return { connect: vi.fn() }
    }
  }
  vi.stubGlobal('MediaRecorder', FakeRecorder)
  vi.stubGlobal('AudioContext', FakeAudioContext)
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: {
      getUserMedia: async () => {
        const track = { stop: vi.fn() }
        tracks.push(track)
        return { getTracks: () => [track] } as unknown as MediaStream
      },
    },
  })
  try {
    const { result, unmount } = renderHook(() => useVoiceRecorder())
    await act(() => result.current.start())
    act(() => result.current.cancel())
    expect(tracks[0]?.stop).toHaveBeenCalledOnce()
    await act(() => result.current.start())
    act(() => recorders[0]?.onstop?.())
    expect(result.current.state.status).toBe('recording')
    expect(tracks[1]?.stop).not.toHaveBeenCalled()
    unmount()
    expect(tracks[1]?.stop).toHaveBeenCalledOnce()
  } finally {
    vi.unstubAllGlobals()
  }
})
