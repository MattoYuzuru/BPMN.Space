import { getModelChoice, useModelChoiceStore } from './choice'

beforeEach(() => {
  window.localStorage.clear()
  useModelChoiceStore.setState({ choices: {} })
})

describe('запомненный выбор модели', () => {
  it('хранится отдельно для каждого пользователя и переживает перезагрузку', () => {
    useModelChoiceStore.getState().set('u1', { credentialId: 'c1', model: 'gpt-4o' })
    useModelChoiceStore.setState({ choices: {} }) // «перезагрузка»: память пуста
    expect(getModelChoice('u1')).toEqual({ credentialId: 'c1', model: 'gpt-4o' })
    expect(getModelChoice('u2')).toBeNull()
    expect(getModelChoice(undefined)).toBeNull()
  })

  it('повреждённая запись не ломает приложение', () => {
    window.localStorage.setItem('arkhitektor:model-choice:u1', '{oops')
    expect(getModelChoice('u1')).toBeNull()
  })

  it('удаление ключа забывает выбор, который на него указывал', () => {
    const store = useModelChoiceStore.getState()
    store.set('u1', { credentialId: 'c1', model: 'm' })
    store.set('u2', { credentialId: 'c2', model: 'm' })
    store.forget('c1')
    expect(getModelChoice('u1')).toBeNull()
    expect(getModelChoice('u2')).not.toBeNull()
  })
})
