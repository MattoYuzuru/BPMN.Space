import { create } from 'zustand'
import type { ChecklistItemKey } from '@/entities/onboarding'

/** Сколько секунд пункт считается «только что отмеченным»: строка в панели показывает это движением. */
export const RECENT_MS = 5000

interface RecentState {
  /** Когда (по часам браузера) пункт заметили выполненным. */
  at: Partial<Record<ChecklistItemKey, number>>
  mark: (keys: readonly ChecklistItemKey[], now?: number) => void
  clear: () => void
}

/**
 * Пункты, которые стали выполненными только что. Наполняет `OnboardingWatcher` (он один сравнивает
 * ответы сервера), читает панель: если её открыли из уведомления «Открыть», галочка проявится
 * на глазах, а не окажется уже стоящей.
 */
export const useRecentItems = create<RecentState>((set) => ({
  at: {},
  mark: (keys, now = Date.now()) =>
    set((state) => ({
      at: { ...state.at, ...Object.fromEntries(keys.map((key) => [key, now])) },
    })),
  clear: () => set({ at: {} }),
}))

/** Пункт отмечен недавно. */
export function isRecent(
  at: Partial<Record<ChecklistItemKey, number>>,
  key: ChecklistItemKey,
  now = Date.now(),
): boolean {
  const marked = at[key]
  return marked !== undefined && now - marked < RECENT_MS
}
