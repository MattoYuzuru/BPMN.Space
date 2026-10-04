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
  /** Учебный проект по данным сервера: сигналы прогонов чужих проектов не в счёт. */
  serverProjectId: string | null
  runStatus: 'queued' | 'running' | null
  runResult: RunResult | null
  /** «Повторить» запустил новый прогон, а он ещё не стартовал: старые данные проекта — не итог. */
  retryPending: boolean
  /** Вопрос шага 7, закреплённый при входе в шаг: прожектор не прыгает на соседнюю карточку. */
  pickedId: string | null
  /** Вопрос, на который ответили в шаге 7: в шаге 8 он не нужен. */
  answeredId: string | null
  shareCreated: boolean
}

interface TourSessionActions {
  setRunResult: (result: RunResult | null) => void
  setProjectId: (id: string | null) => void
  setServerProjectId: (id: string | null) => void
  setRetryPending: (pending: boolean) => void
  setPickedId: (id: string | null) => void
  reset: () => void
}

const initial: TourSessionState = {
  projectId: null,
  serverProjectId: null,
  runStatus: null,
  runResult: null,
  retryPending: false,
  pickedId: null,
  answeredId: null,
  shareCreated: false,
}

/**
 * Что тур запомнил за заход: проект, итог прогона, отвеченный вопрос. Живёт в памяти — после
 * перезагрузки всё восстанавливается с сервера и по данным проекта (`TourRoot`).
 */
export const useTourSession = create<TourSessionState & TourSessionActions>((put) => ({
  ...initial,
  setRunResult: (runResult) => put({ runResult }),
  setProjectId: (projectId) => put({ projectId }),
  setServerProjectId: (serverProjectId) => put({ serverProjectId }),
  setRetryPending: (retryPending) => put({ retryPending }),
  setPickedId: (pickedId) => put({ pickedId }),
  // Проект с сервера переживает сброс: он принадлежит не заходу, а пользователю.
  reset: () => put((state) => ({ ...initial, serverProjectId: state.serverProjectId })),
}))

/** Забыть всё, что относится к прошлому заходу (новый тур, «Начать заново», конец тура). */
export function resetTourSession() {
  useTourSession.getState().reset()
}

/**
 * Запись сигналов в сессию. Подписка живёт с загрузкой модуля — раньше, чем хост тура, поэтому
 * к моменту, когда хост решает, какой шаг показать дальше, итог прогона и учебный проект уже
 * записаны. Вне тура сигналы не записываются.
 */
subscribeOnboardingSignals((signal) => {
  const tour = useTourStore.getState()
  if (tour.status !== 'active') return
  const state = useTourSession.getState()
  const put = useTourSession.setState
  const projectId = state.projectId ?? state.serverProjectId
  // Прогон другого проекта (например, пока тур на паузе) учебный не затрагивает.
  const foreign = (signalProject: string) => !projectId || signalProject !== projectId
  switch (signal.type) {
    case 'project.created':
      if (tour.stepKey === 'project.create') put({ projectId: signal.id })
      break
    case 'run.started':
      if (foreign(signal.projectId)) break
      put({ runResult: null, runStatus: null, retryPending: false })
      break
    case 'run.status':
      if (foreign(signal.projectId)) break
      put({ runStatus: signal.status })
      break
    case 'run.finished':
      if (foreign(signal.projectId)) break
      put({
        runStatus: null,
        retryPending: false,
        runResult: {
          status: signal.status,
          openQuestions: signal.openQuestions,
          hasDiagram: signal.hasDiagram,
        },
      })
      break
    case 'question.answered':
      if (tour.stepKey === 'question.answer') put({ answeredId: signal.id })
      break
    case 'share.created':
      if (tour.stepKey === 'share.create') put({ shareCreated: true })
      break
    default:
      break
  }
})
