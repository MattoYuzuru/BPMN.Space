import { startTour } from '../tour'
import { loadAgentTour } from './persistence'
import { agentTourSteps, FIRST_AGENT_STEP } from './steps'

/** Отдельный владелец стора: агентский тур не должен трогать серверный прогресс. */
export const AGENT_TOUR_ID = 'agent'

/** Шаг сохранённого тура всё ещё существует: сценарий мог измениться. */
export function isAgentTourStepKey(key: string | null): key is string {
  return Boolean(key && agentTourSteps.some((step) => step.key === key))
}

/**
 * Запустить агентский тур. Вызывается только явно — кнопкой в разделе «Доступ для агентов»,
 * не при входе. Незаконченный тур (status=active) продолжается с сохранённого шага; пройденный
 * или отклонённый начинается заново.
 */
export function startAgentTour(): void {
  const saved = loadAgentTour()
  const resume = saved.status === 'active' && isAgentTourStepKey(saved.step)
  startTour(resume && saved.step ? saved.step : FIRST_AGENT_STEP, {
    restored: resume,
    tourId: AGENT_TOUR_ID,
  })
}
