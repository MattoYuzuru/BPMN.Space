import { Route } from '@/routes/login'

const validate = (search: Record<string, unknown>) =>
  (Route.options.validateSearch as (s: Record<string, unknown>) => unknown)(search)

describe('/login: параметры адреса', () => {
  it('mode=register включает регистрацию, всё остальное — вход', () => {
    expect(validate({ mode: 'register' })).toMatchObject({ mode: 'register' })
    expect(validate({ mode: 'login' })).toMatchObject({ mode: undefined })
    expect(validate({ mode: ['register'] })).toMatchObject({ mode: undefined })
    expect(validate({})).toMatchObject({ mode: undefined })
  })

  it('сохраняет проверенный redirect вместе с режимом и отбрасывает чужой', () => {
    expect(validate({ mode: 'register', redirect: '/projects/p-1' })).toEqual({
      mode: 'register',
      redirect: '/projects/p-1',
    })
    expect(validate({ mode: 'register', redirect: 'https://evil.example/' })).toEqual({
      mode: 'register',
      redirect: undefined,
    })
  })
})
