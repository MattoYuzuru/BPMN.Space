import { registerAccountReset, resetAccountState } from './account-reset'

describe('сброс состояния аккаунта', () => {
  it('вызывает все зарегистрированные сбросы и учитывает отписку', () => {
    const first = vi.fn()
    const second = vi.fn()
    const off = registerAccountReset(first)
    const offSecond = registerAccountReset(second)
    resetAccountState()
    off()
    resetAccountState()
    offSecond()
    expect(first).toHaveBeenCalledTimes(1)
    expect(second).toHaveBeenCalledTimes(2)
  })
})
