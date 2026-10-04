import type { RunEvent } from './model'
import { openRunStream, retryDelay } from './stream'

/** Поддельный EventSource: тест сам «присылает» события и обрывы. */
class FakeEventSource {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSED = 2
  static instances: FakeEventSource[] = []
  readyState = FakeEventSource.CONNECTING
  onopen: (() => void) | null = null
  private listeners = new Map<string, ((event: Event) => void)[]>()

  readonly url: string

  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }
  addEventListener(type: string, listener: (event: Event) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener])
  }
  close() {
    this.readyState = FakeEventSource.CLOSED
  }
  emit(type: string, data: unknown, id: number) {
    const event = new MessageEvent(type, { data: JSON.stringify(data), lastEventId: String(id) })
    for (const listener of this.listeners.get(type) ?? []) listener(event)
  }
  drop(state: number) {
    this.readyState = state
    for (const listener of this.listeners.get('error') ?? []) listener(new Event('error'))
  }
}

const Impl = FakeEventSource as unknown as typeof EventSource

beforeEach(() => {
  FakeEventSource.instances = []
  vi.useFakeTimers()
})
afterEach(() => vi.useRealTimers())

describe('openRunStream', () => {
  it('разбирает события и закрывается на done', () => {
    const events: RunEvent[] = []
    openRunStream('r1', { onEvent: (event) => events.push(event) }, { EventSourceImpl: Impl })
    const source = FakeEventSource.instances[0]
    expect(source?.url).toBe('/api/v1/runs/r1/events')
    source?.emit('stage', { stage: 'extracting', label: 'Ищу', progress: 0.3 }, 1)
    source?.emit('error', { message: 'сбой' }, 2)
    source?.emit('done', { run: { id: 'r1' } }, 3)
    expect(events.map((event) => [event.type, event.id])).toEqual([
      ['stage', 1],
      ['error', 2],
      ['done', 3],
    ])
    expect(source?.readyState).toBe(FakeEventSource.CLOSED)
  })

  it('переподключается, если поток закрыт, и сдаётся после лимита', () => {
    const onLost = vi.fn()
    openRunStream('r1', { onEvent: () => {}, onLost }, { EventSourceImpl: Impl, maxAttempts: 2 })
    // Браузер переподключается сам (CONNECTING) — новый EventSource не нужен.
    FakeEventSource.instances[0]?.drop(FakeEventSource.CONNECTING)
    expect(FakeEventSource.instances).toHaveLength(1)

    FakeEventSource.instances[0]?.drop(FakeEventSource.CLOSED)
    vi.advanceTimersByTime(retryDelay(0))
    expect(FakeEventSource.instances).toHaveLength(2)

    FakeEventSource.instances[1]?.drop(FakeEventSource.CLOSED)
    vi.advanceTimersByTime(retryDelay(1))
    expect(FakeEventSource.instances).toHaveLength(3)

    FakeEventSource.instances[2]?.drop(FakeEventSource.CLOSED)
    expect(onLost).toHaveBeenCalledOnce()
  })

  it('сессия закончилась: вместо повторных подключений сообщаем об этом один раз', async () => {
    const onLost = vi.fn()
    const onSessionExpired = vi.fn()
    const checkSession = vi.fn(async () => false)
    openRunStream(
      'r1',
      { onEvent: () => {}, onLost, onSessionExpired },
      { EventSourceImpl: Impl, checkSession },
    )
    FakeEventSource.instances[0]?.drop(FakeEventSource.CLOSED)
    await vi.advanceTimersByTimeAsync(retryDelay(0))

    expect(checkSession).toHaveBeenCalledOnce()
    expect(onSessionExpired).toHaveBeenCalledOnce()
    expect(onLost).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(FakeEventSource.instances).toHaveLength(1)
  })

  it('сессия жива: переподключаемся как обычно', async () => {
    const checkSession = vi.fn(async () => true)
    openRunStream('r1', { onEvent: () => {} }, { EventSourceImpl: Impl, checkSession })
    FakeEventSource.instances[0]?.drop(FakeEventSource.CLOSED)
    await vi.advanceTimersByTimeAsync(retryDelay(0))

    expect(FakeEventSource.instances).toHaveLength(2)
  })

  it('сбой самой проверки не мешает переподключению', async () => {
    const checkSession = vi.fn(async () => {
      throw new Error('сеть')
    })
    openRunStream('r1', { onEvent: () => {} }, { EventSourceImpl: Impl, checkSession })
    FakeEventSource.instances[0]?.drop(FakeEventSource.CLOSED)
    await vi.advanceTimersByTimeAsync(retryDelay(0))

    expect(FakeEventSource.instances).toHaveLength(2)
  })

  it('отписка во время проверки сессии отменяет переподключение', async () => {
    let answer: (alive: boolean) => void = () => {}
    const checkSession = () =>
      new Promise<boolean>((resolve) => {
        answer = resolve
      })
    const close = openRunStream(
      'r1',
      { onEvent: () => {} },
      { EventSourceImpl: Impl, checkSession },
    )
    FakeEventSource.instances[0]?.drop(FakeEventSource.CLOSED)
    await vi.advanceTimersByTimeAsync(retryDelay(0))
    close()
    answer(true)
    await vi.advanceTimersByTimeAsync(0)

    expect(FakeEventSource.instances).toHaveLength(1)
  })

  it('отписка закрывает поток и отменяет повтор', () => {
    const close = openRunStream('r1', { onEvent: () => {} }, { EventSourceImpl: Impl })
    FakeEventSource.instances[0]?.drop(FakeEventSource.CLOSED)
    close()
    vi.advanceTimersByTime(10_000)
    expect(FakeEventSource.instances).toHaveLength(1)
  })

  it('растягивает паузы между попытками до 10 секунд', () => {
    expect([0, 1, 2, 3, 4, 8].map(retryDelay)).toEqual([1000, 2000, 4000, 8000, 10_000, 10_000])
  })
})
