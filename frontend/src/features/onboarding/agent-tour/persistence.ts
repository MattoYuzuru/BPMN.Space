import type { TourPersistence, TourStatus } from '../tour/types'

/** Ключ в localStorage: прогресс клиентского тура не уходит на сервер. */
export const AGENT_TOUR_STORAGE_KEY = 'bps.agent-tour.v1'

export interface AgentTourSaved {
  status: TourStatus
  step: string | null
}

const STATUSES: readonly TourStatus[] = ['pending', 'active', 'completed', 'dismissed']

/** Прочитанное состояние: битое или чужое значение считается «ещё не начинали». */
export function loadAgentTour(): AgentTourSaved {
  try {
    const raw = globalThis.localStorage?.getItem(AGENT_TOUR_STORAGE_KEY)
    if (!raw) return { status: 'pending', step: null }
    const parsed: unknown = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return { status: 'pending', step: null }
    const status = (parsed as { status?: unknown }).status
    const step = (parsed as { step?: unknown }).step
    if (typeof status !== 'string' || !STATUSES.includes(status as TourStatus)) {
      return { status: 'pending', step: null }
    }
    return { status: status as TourStatus, step: typeof step === 'string' ? step : null }
  } catch {
    // Приватный режим или запрет хранилища: тур работает без сохранения.
    return { status: 'pending', step: null }
  }
}

export function saveAgentTour(state: AgentTourSaved): void {
  try {
    globalThis.localStorage?.setItem(AGENT_TOUR_STORAGE_KEY, JSON.stringify(state))
  } catch {
    // Сохранить не удалось — не мешаем обучению.
  }
}

/** Забыть прогресс (тесты, «Пройти снова» с чистого листа). */
export function resetAgentTour(): void {
  try {
    globalThis.localStorage?.removeItem(AGENT_TOUR_STORAGE_KEY)
  } catch {
    // Хранилище недоступно — сбрасывать нечего.
  }
}

/**
 * Хранилище тура в localStorage. Шаг пишется при входе, статус — при старте и завершении;
 * `load` движок не использует (`restore={false}`), восстановление делает `startAgentTour`.
 */
export const agentTourPersistence: TourPersistence = {
  load: async () => loadAgentTour(),
  saveStep: (step) => {
    saveAgentTour({ ...loadAgentTour(), status: 'active', step })
    return undefined
  },
  setStatus: (status) => {
    saveAgentTour({ status, step: status === 'active' ? loadAgentTour().step : null })
    return undefined
  },
}
