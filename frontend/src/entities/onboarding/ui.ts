import { create } from 'zustand'

/**
 * Нейтральное состояние интерфейса онбординга. Через него меню аккаунта, плашка прогресса,
 * уведомления и сценарий тура просят открыть панель «Начало работы», не импортируя друг друга.
 */
interface OnboardingUiState {
  /** Открыта ли боковая панель «Начало работы». */
  checklistOpen: boolean
  openChecklist: () => void
  closeChecklist: () => void
}

export const useOnboardingUi = create<OnboardingUiState>((set) => ({
  checklistOpen: false,
  openChecklist: () => set({ checklistOpen: true }),
  closeChecklist: () => set({ checklistOpen: false }),
}))
