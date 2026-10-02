import { runEventsUrl } from '@/shared/api/client'
import type { RunEvent, RunEventType } from './model'

const EVENT_TYPES: readonly RunEventType[] = [
  'stage',
  'question',
  'summary',
  'version',
  'error',
  'done',
]

/** Пауза перед повторным подключением: 1, 2, 4, 8 с, дальше 10 с. */
export function retryDelay(attempt: number): number {
  return Math.min(1000 * 2 ** attempt, 10_000)
}

export interface RunStreamHandlers {
  onEvent: (event: RunEvent) => void
  /** Поток не удалось восстановить за отведённые попытки. */
  onLost?: () => void
}

export interface RunStreamOptions {
  maxAttempts?: number
  /** Подмена EventSource в тестах. */
  EventSourceImpl?: typeof EventSource
}

/**
 * Подписка на события прогона (SSE). Обрывы связи браузер переживает сам и продолжает с
 * Last-Event-ID; если поток закрыт совсем, переподключаемся с паузой — сервер пришлёт историю
 * заново, а редьюсер отбросит уже обработанные события. После `done` поток закрывается.
 * Возвращает функцию отписки.
 */
export function openRunStream(
  runId: string,
  handlers: RunStreamHandlers,
  { maxAttempts = 8, EventSourceImpl = EventSource }: RunStreamOptions = {},
): () => void {
  let source: EventSource | null = null
  let timer: ReturnType<typeof setTimeout> | undefined
  let attempt = 0
  let finished = false

  const close = () => {
    finished = true
    clearTimeout(timer)
    source?.close()
    source = null
  }

  const connect = () => {
    if (finished) return
    const current = new EventSourceImpl(runEventsUrl(runId))
    source = current
    current.onopen = () => {
      attempt = 0
    }
    for (const type of EVENT_TYPES) {
      current.addEventListener(type, (raw: Event) => {
        // Событие прогона `error` и сетевая ошибка EventSource приходят под одним именем.
        if (!(raw instanceof MessageEvent) || typeof raw.data !== 'string' || !raw.data) {
          if (type === 'error') onConnectionError(current)
          return
        }
        let data: unknown
        try {
          data = JSON.parse(raw.data)
        } catch {
          return
        }
        const id = Number.parseInt(raw.lastEventId, 10)
        handlers.onEvent({ type, id: Number.isNaN(id) ? 0 : id, data } as RunEvent)
        if (type === 'done') close()
      })
    }
  }

  const onConnectionError = (current: EventSource) => {
    if (finished || current !== source) return
    // CONNECTING — браузер переподключится сам; CLOSED — переподключаемся мы.
    if (current.readyState !== EventSourceImpl.CLOSED) return
    current.close()
    if (attempt >= maxAttempts) {
      finished = true
      handlers.onLost?.()
      return
    }
    timer = setTimeout(connect, retryDelay(attempt))
    attempt += 1
  }

  connect()
  return close
}
