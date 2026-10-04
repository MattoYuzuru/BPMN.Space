import { beforeEach, describe, expect, it } from 'vitest'
import { useCreateProjectDialog } from './model'

beforeEach(() => {
  useCreateProjectDialog.setState({
    open: false,
    loaded: false,
    mode: 'blank',
    title: '',
    lockMode: false,
    minimal: false,
    onboarding: false,
    interceptor: null,
  })
})

describe('useCreateProjectDialog', () => {
  it('show открывает диалог в нужном режиме без особых параметров', () => {
    useCreateProjectDialog.getState().show('example')
    expect(useCreateProjectDialog.getState()).toMatchObject({
      open: true,
      loaded: true,
      mode: 'example',
      title: '',
      lockMode: false,
      minimal: false,
      onboarding: false,
    })
  })

  it('openWith принимает название, фиксацию режима, минимальную форму и метку обучения', () => {
    useCreateProjectDialog.getState().openWith({
      mode: 'blank',
      title: 'Мой первый процесс',
      lockMode: true,
      minimal: true,
      onboarding: true,
    })
    expect(useCreateProjectDialog.getState()).toMatchObject({
      open: true,
      mode: 'blank',
      title: 'Мой первый процесс',
      lockMode: true,
      minimal: true,
      onboarding: true,
    })
  })

  it('подмена: любое открытие (кнопка, палитра) получает параметры обучения; снята — всё как было', () => {
    const { setInterceptor, show } = useCreateProjectDialog.getState()
    setInterceptor((options) => ({
      ...options,
      mode: 'blank',
      title: 'Мой первый процесс',
      lockMode: true,
      minimal: true,
      onboarding: true,
    }))
    show('example')
    expect(useCreateProjectDialog.getState()).toMatchObject({
      mode: 'blank',
      title: 'Мой первый процесс',
      lockMode: true,
      minimal: true,
    })
    setInterceptor(null)
    useCreateProjectDialog.getState().show('blank')
    expect(useCreateProjectDialog.getState()).toMatchObject({
      title: '',
      lockMode: false,
      minimal: false,
      onboarding: false,
    })
  })
})
