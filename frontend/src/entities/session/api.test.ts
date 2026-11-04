import { QueryClient } from '@tanstack/react-query'
import { getModelChoice, useModelChoiceStore } from '@/entities/llm-credential/choice'
import { type Run, useRunStore } from '@/entities/run'
import { dropAccountData } from './api'

describe('смена аккаунта', () => {
  it('сбрасывает хранилища прошлого пользователя, а выбор модели читает заново из его ключа', () => {
    useRunStore.getState().track({ id: 'r-1', project_id: 'p-1', status: 'running' } as Run, true)
    useModelChoiceStore.getState().set('u1', { credentialId: 'c1', model: 'm1' })
    expect(useRunStore.getState().views['p-1']).toBeDefined()

    dropAccountData(new QueryClient())

    expect(useRunStore.getState().views).toEqual({})
    expect(useModelChoiceStore.getState().choices).toEqual({})
    // Память пуста, но выбор остался в localStorage под id владельца.
    expect(getModelChoice('u1')).toEqual({ credentialId: 'c1', model: 'm1' })
    expect(getModelChoice('u2')).toBeNull()
  })
})
