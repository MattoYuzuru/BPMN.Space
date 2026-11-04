import { stopTour, useTourStore } from '../tour'
import { saveAgentTour } from './persistence'
import { startAgentTour } from './store'

beforeEach(() => {
  stopTour()
  localStorage.clear()
})

afterEach(() => stopTour())

describe('запуск агентского тура', () => {
  it('без сохранения начинает с первого шага', () => {
    startAgentTour()
    expect(useTourStore.getState().status).toBe('active')
    expect(useTourStore.getState().stepKey).toBe('agent.tools')
    expect(useTourStore.getState().restored).toBe(false)
  })

  it('незаконченный тур продолжается с сохранённого шага', () => {
    saveAgentTour({ status: 'active', step: 'agent.create-token' })
    startAgentTour()
    expect(useTourStore.getState().stepKey).toBe('agent.create-token')
    expect(useTourStore.getState().restored).toBe(true)
  })

  it('пройденный и отклонённый тур начинается заново', () => {
    for (const status of ['completed', 'dismissed'] as const) {
      stopTour()
      saveAgentTour({ status, step: null })
      startAgentTour()
      expect(useTourStore.getState().stepKey).toBe('agent.tools')
      expect(useTourStore.getState().restored).toBe(false)
    }
  })

  it('незнакомый сохранённый шаг не ломает запуск', () => {
    saveAgentTour({ status: 'active', step: 'agent.removed-step' })
    startAgentTour()
    expect(useTourStore.getState().stepKey).toBe('agent.tools')
  })
})
