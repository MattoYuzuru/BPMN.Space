import { QueryClient } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { type OnboardingState, onboardingKeys } from '@/entities/onboarding'
import { createTourPersistence } from './create-persistence'
import { resetTourSession, useTourSession } from './session'

const tour = (patch: Partial<NonNullable<OnboardingState['tour']>> = {}) => ({
  status: 'active' as const,
  step: 'project.create' as const,
  project_id: null,
  updated_at: '2026-10-04T10:00:00Z',
  ...patch,
})

function setup(state: OnboardingState | null) {
  const client = new QueryClient()
  if (state) client.setQueryData(onboardingKeys.user('u1'), state)
  const update = vi.fn().mockResolvedValue(undefined)
  return { client, update, persistence: createTourPersistence({ client, userId: 'u1', update }) }
}

beforeEach(() => resetTourSession())

describe('createTourPersistence', () => {
  it('записывает смену шага и не повторяет шаг, который сервер уже знает', () => {
    const { persistence, update } = setup({ enabled: true, tour: tour() })
    persistence.saveStep('project.create')
    expect(update).not.toHaveBeenCalled()
    persistence.saveStep('sources.sample')
    expect(update).toHaveBeenCalledWith({ step: 'sources.sample' })
  })

  it('не отправляет «active», если тур уже активен; завершение и отказ отправляет', () => {
    const { persistence, update } = setup({ enabled: true, tour: tour() })
    persistence.setStatus('active')
    expect(update).not.toHaveBeenCalled()
    persistence.setStatus('completed')
    persistence.setStatus('dismissed')
    expect(update).toHaveBeenNthCalledWith(1, { status: 'completed' })
    expect(update).toHaveBeenNthCalledWith(2, { status: 'dismissed' })
  })

  it('сообщает учебный проект вместе с первым шагом после создания', () => {
    const { persistence, update } = setup({ enabled: true, tour: tour() })
    useTourSession.getState().setProjectId('p1')
    persistence.saveStep('sources.sample')
    expect(update).toHaveBeenCalledWith({ step: 'sources.sample', project_id: 'p1' })
  })

  it('проект, о котором сервер уже знает, повторно не отправляется', () => {
    const { persistence, update } = setup({ enabled: true, tour: tour({ project_id: 'p1' }) })
    useTourSession.getState().setProjectId('p1')
    persistence.saveStep('sources.text')
    expect(update).toHaveBeenCalledWith({ step: 'sources.text' })
  })

  it('load отдаёт статус и шаг с сервера, а пустое состояние — как «ещё не предлагали»', async () => {
    const { client, persistence } = setup(null)
    client.setQueryData(onboardingKeys.user('u1'), {
      enabled: true,
      tour: tour({ step: 'question.answer' }),
    })
    const fresh = vi.spyOn(client, 'fetchQuery').mockResolvedValue({
      enabled: true,
      tour: tour({ step: 'question.answer' }),
    })
    expect(await persistence.load()).toEqual({ status: 'active', step: 'question.answer' })
    fresh.mockResolvedValue({ enabled: true })
    expect(await persistence.load()).toEqual({ status: 'pending', step: null })
  })
})
