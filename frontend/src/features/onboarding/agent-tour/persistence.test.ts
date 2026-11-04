import {
  AGENT_TOUR_STORAGE_KEY,
  agentTourPersistence,
  loadAgentTour,
  resetAgentTour,
  saveAgentTour,
} from './persistence'

beforeEach(() => localStorage.clear())

describe('хранение агентского тура', () => {
  it('по умолчанию тур не начат', () => {
    expect(loadAgentTour()).toEqual({ status: 'pending', step: null })
  })

  it('сохраняет шаг и статус, читает их обратно', () => {
    saveAgentTour({ status: 'active', step: 'agent.create-token' })
    expect(loadAgentTour()).toEqual({ status: 'active', step: 'agent.create-token' })
    expect(JSON.parse(localStorage.getItem(AGENT_TOUR_STORAGE_KEY) ?? '{}')).toEqual({
      status: 'active',
      step: 'agent.create-token',
    })
  })

  it('битое значение и незнакомый статус — «ещё не начинали»', () => {
    localStorage.setItem(AGENT_TOUR_STORAGE_KEY, '{не json')
    expect(loadAgentTour()).toEqual({ status: 'pending', step: null })
    localStorage.setItem(AGENT_TOUR_STORAGE_KEY, JSON.stringify({ status: 'что-то', step: 1 }))
    expect(loadAgentTour()).toEqual({ status: 'pending', step: null })
  })

  it('сброс забывает прогресс', () => {
    saveAgentTour({ status: 'completed', step: null })
    resetAgentTour()
    expect(loadAgentTour()).toEqual({ status: 'pending', step: null })
  })

  it('TourPersistence: вход в шаг делает тур активным, завершение убирает шаг', async () => {
    agentTourPersistence.saveStep('agent.copy-command')
    expect(await agentTourPersistence.load()).toEqual({
      status: 'active',
      step: 'agent.copy-command',
    })
    agentTourPersistence.setStatus('completed')
    expect(await agentTourPersistence.load()).toEqual({ status: 'completed', step: null })
  })
})
