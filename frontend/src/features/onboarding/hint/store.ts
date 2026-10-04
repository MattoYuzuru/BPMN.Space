import { create } from 'zustand'
import type { AnchorRef } from '@/shared/lib/tour-anchors'

export interface HintRequest {
  anchor: AnchorRef
  text: string
  /** Готовит экран: развернуть панель, выбрать вопрос (`selectQuestion(id, { focus: true })`). */
  prepare?: () => void
}

interface HintState {
  current: (HintRequest & { id: number }) | null
  show: (request: HintRequest) => void
  hide: () => void
}

let counter = 0

export const useHintStore = create<HintState>((set) => ({
  current: null,
  show: (request) => {
    counter += 1
    set({ current: { ...request, id: counter } })
  },
  hide: () => set({ current: null }),
}))

/**
 * Показать подсказку-указатель: пульсирующее кольцо на элементе и поповер с текстом, без
 * затемнения экрана. Одна подсказка в момент времени — новая заменяет прежнюю. Якорь не найден
 * за 5 с — подсказка показывается обычным уведомлением с тем же текстом.
 */
export function showHint(request: HintRequest): void {
  useHintStore.getState().show(request)
}

export function hideHint(): void {
  useHintStore.getState().hide()
}
