import { create } from 'zustand'
import { subscribeOnboardingSignals } from '@/shared/lib/onboarding-signals'
import { useTourStore } from './store'

/** Итог прогона, по которому сценарий выбирает ветку. */
export interface RunResult {
  status: string
  openQuestions: number
  hasDiagram: boolean
}

interface TourSessionState {
  /** Учебный проект, созданный в этом заходе (сервер узнает о нём вместе с первым шагом). */
  projectId: string | null
  /** Прогон уже запускали с начала тура: итог берётся из сигнала, а не восстанавливается по данным. */
  runSeen: boolean
  runStatus: 'queued' | 'running' | null
  runResult: RunResult | null
  /** Вопрос, на который ответили в шаге 7: в шаге 8 он не нужен. */
  answeredId: string | null
  shareCreated: boolean
}

interface TourSessionActions {
  setRunResult: (result: RunResult | null) => void
  setProjectId: (id: string | null) => void
  reset: () => void
}

const initial: TourSessionState = {
  projectId: null,
  runSeen: false,
  runStatus: null,
  runResult: null,
  answeredId: null,
  shareCreated: false,
}

/**
 * Что тур запомнил за заход: проект, итог прогона, отвеченный вопрос. Живёт в памяти — после
 * перезагрузки всё восстанавливается с сервера и по данным проекта (`TourRoot`).
 */
export const useTourSession = create<TourSessionState & TourSessionActions>((set) => ({
  ...initial,
  setRunResult: (runResult) => set({ runResult }),
  setProjectId: (projectId) => set({ projectId }),
  reset: () => set({ ...initial }),
}))

/** Забыть всё, что относится к прошлому заходу (новый тур, «Начать заново», конец тура). */
export function resetTourSession() {
  useTourSession.getState().reset()
}

/**
 * Запись сигналов в сессию. Подписка живёт с загрузкой модуля — раньше, чем хост тура, поэтому
 * к моменту, когда хост решает, какой шаг показывать после сигнала, сессия уже обновлена.
 * Вне тура сигналы не записываются.
 */
subscribeOnboardingSignals((signal) => {
  const tour = useTourStore.getState()
  if (tour.status !== 'active') return
  const set = useTourSession.setState
  switch (signal.type) {
    case 'project.created':
      if (tour.stepKey === 'project.create') set({ projectId: signal.id })
      break
    case 'run.started':
      set({ runSeen: true, runResult: null, runStatus: null })
      break
    case 'run.status':
      set({ runStatus: signal.status })
      break
    case 'run.finished':
      set({
        runStatus: null,
        runResult: {
          status: signal.status,
          openQuestions: signal.openQuestions,
          hasDiagram: signal.hasDiagram,
        },
      })
      break
    case 'question.answered':
      if (tour.stepKey === 'question.answer') set({ answeredId: signal.id })
      break
    case 'share.created':
      if (tour.stepKey === 'share.create') set({ shareCreated: true })
      break
    default:
      break
  }
})
