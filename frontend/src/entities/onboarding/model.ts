import type { Schemas } from '@/shared/api/client'
import { CHECKLIST_TOTAL, type ChecklistItemKey } from './items'

export type OnboardingState = Schemas['OnboardingState']
export type ChecklistEntry = Schemas['ChecklistEntry']
export type TourState = Schemas['TourState']
export type OnboardingTarget = Schemas['OnboardingTarget']
export type TargetHint = Schemas['TargetHint']

/** Онбординг включён для пользователя (на сервере есть аккаунты и флаг не выключен). */
export const isOnboardingEnabled = (state: OnboardingState | undefined): boolean =>
  Boolean(state?.enabled)

/** Ключи отмеченных пунктов. */
export function completedKeys(state: OnboardingState | undefined): Set<ChecklistItemKey> {
  return new Set((state?.checklist?.items ?? []).map((entry) => entry.key))
}

export const isItemDone = (state: OnboardingState | undefined, key: ChecklistItemKey): boolean =>
  completedKeys(state).has(key)

export interface ChecklistProgress {
  done: number
  total: number
  complete: boolean
}

/** Прогресс «N из 12»; чек-лист завершён, когда отмечены все пункты. */
export function checklistProgress(state: OnboardingState | undefined): ChecklistProgress {
  const done = completedKeys(state).size
  return { done, total: CHECKLIST_TOTAL, complete: done >= CHECKLIST_TOTAL }
}

/** Идёт ли тур прямо сейчас. */
export const isTourActive = (state: OnboardingState | undefined): boolean =>
  state?.tour?.status === 'active'

/** Тур ещё ни разу не предлагали: пора показать приветствие. */
export const shouldOfferTour = (state: OnboardingState | undefined): boolean =>
  Boolean(state?.enabled) && state?.tour?.status === 'pending'

/** Плашка прогресса нужна, пока чек-лист не завершён и не скрыт. */
export function isChecklistVisible(state: OnboardingState | undefined): boolean {
  if (!state?.enabled || !state.checklist) return false
  return !state.checklist.hidden && !checklistProgress(state).complete
}

/** Состояние с добавленным пунктом (оптимистичная отметка); повтор ничего не меняет. */
export function withCompletedItem(
  state: OnboardingState,
  key: ChecklistItemKey,
  source: ChecklistEntry['source'],
  completedAt: string,
): OnboardingState {
  if (!state.checklist || isItemDone(state, key)) return state
  return {
    ...state,
    checklist: {
      ...state.checklist,
      items: [...state.checklist.items, { key, completed_at: completedAt, source }],
    },
  }
}
