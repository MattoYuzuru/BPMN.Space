import { create } from 'zustand'
import type { OnboardingSignal } from '@/shared/lib/onboarding-signals'
import type { SignalMemory } from './types'

export interface TourState {
  /** idle — тура нет; active — идёт (в том числе на паузе). */
  status: 'idle' | 'active'
  stepKey: string | null
  page: number
  /** Пользователь ушёл с экрана шага: оверлей скрыт, внизу пилюля «Вернуться к обучению». */
  paused: boolean
  /** Подтверждение завершения показано в карточке. */
  confirming: boolean
  /** Пройденные шаги (для «Назад»). */
  history: string[]
  /** Прочитанные страницы `ключ:страница` — при возврате печатаются сразу. */
  readPages: Record<string, true>
  /** Сигналы текущего шага. */
  seen: SignalMemory
  enteredAt: number
  /** Счётчик кликов по затемнению: карточка подсвечивает рамку. */
  attention: number
  /** Шаг взят из восстановления: сохранять его на сервер повторно не нужно. */
  restored: boolean
}

interface TourActions {
  start: (stepKey: string, options?: { restored?: boolean }) => void
  /** Переход на шаг; `history` — новая история (контроллер решает, добавлять ли текущий шаг). */
  enter: (stepKey: string, history: string[]) => void
  setPage: (page: number) => void
  setPaused: (paused: boolean) => void
  setConfirming: (confirming: boolean) => void
  markRead: (stepKey: string, page: number) => void
  recordSignal: (signal: OnboardingSignal) => void
  bumpAttention: () => void
  stop: () => void
}

const initial: TourState = {
  status: 'idle',
  stepKey: null,
  page: 0,
  paused: false,
  confirming: false,
  history: [],
  readPages: {},
  seen: {},
  enteredAt: 0,
  attention: 0,
  restored: false,
}

/** Состояние тура. Один тур на приложение; сценарий запускает его через `startTour`. */
export const useTourStore = create<TourState & TourActions>((set) => ({
  ...initial,
  start: (stepKey, options) =>
    set({
      ...initial,
      status: 'active',
      stepKey,
      enteredAt: Date.now(),
      restored: options?.restored ?? false,
    }),
  enter: (stepKey, history) =>
    set({
      stepKey,
      history,
      page: 0,
      seen: {},
      confirming: false,
      enteredAt: Date.now(),
      restored: false,
    }),
  setPage: (page) => set({ page }),
  setPaused: (paused) => set({ paused }),
  setConfirming: (confirming) => set({ confirming }),
  markRead: (stepKey, page) =>
    set((state) => ({ readPages: { ...state.readPages, [`${stepKey}:${page}`]: true } })),
  recordSignal: (signal) =>
    set((state) => ({ seen: { ...state.seen, [signal.type]: signal } as SignalMemory })),
  bumpAttention: () => set((state) => ({ attention: state.attention + 1 })),
  stop: () => set({ ...initial }),
}))

/** Запустить тур с шага `stepKey`. Сохранение статуса на сервере — на стороне сценария и TourHost. */
export function startTour(stepKey: string, options?: { restored?: boolean }): void {
  useTourStore.getState().start(stepKey, options)
}

/** Остановить тур без записи на сервер (например, при выходе из аккаунта). */
export function stopTour(): void {
  useTourStore.getState().stop()
}
