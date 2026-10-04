import { create } from 'zustand'

interface OnboardingUi {
  /** Боковая панель чек-листа «Начало работы» открыта. */
  checklistOpen: boolean
  openChecklist: () => void
  closeChecklist: () => void
}

/**
 * Нейтральная точка открытия панели чек-листа: тур (финал «Открыть чек-лист»), меню аккаунта и
 * плашка не знают друг о друге, а панель подписывается на `checklistOpen`.
 */
export const useOnboardingUi = create<OnboardingUi>((set) => ({
  checklistOpen: false,
  openChecklist: () => set({ checklistOpen: true }),
  closeChecklist: () => set({ checklistOpen: false }),
}))
