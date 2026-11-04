import { create } from 'zustand'

interface OnboardingUi {
  /** Боковая панель чек-листа «Начало работы» открыта. */
  checklistOpen: boolean
  openChecklist: () => void
  closeChecklist: () => void
  /** Растёт на каждую просьбу запустить клиентский тур для агентов. */
  agentTourRequest: number
  openAgentTour: () => void
}

/**
 * Нейтральная точка открытия обучения: панель чек-листа, агентский тур, меню аккаунта и плашка
 * не знают друг о друге, а подписчики реагируют на `checklistOpen` и `agentTourRequest`.
 * `agentTourRequest` — только просьба: тур запускается явно из «Доступа для агентов» и никогда
 * сам при входе.
 */
export const useOnboardingUi = create<OnboardingUi>((set) => ({
  checklistOpen: false,
  openChecklist: () => set({ checklistOpen: true }),
  closeChecklist: () => set({ checklistOpen: false }),
  agentTourRequest: 0,
  openAgentTour: () => set((state) => ({ agentTourRequest: state.agentTourRequest + 1 })),
}))
