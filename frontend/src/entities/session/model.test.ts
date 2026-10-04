import { describe, expect, it } from 'vitest'
import { ApiError } from '@/shared/api/client'
import {
  authFormError,
  emailInitialsName,
  loginSearch,
  needsLogin,
  sanitizeRedirect,
  validateAuthForm,
} from './model'

describe('sanitizeRedirect', () => {
  it.each([
    ['/projects/abc', '/projects/abc'],
    ['/projects/abc?question=q1&mark=2', '/projects/abc?question=q1&mark=2'],
    ['/?q=схема', '/?q=схема'],
  ])('пропускает путь этого же сайта %s', (input, expected) => {
    expect(sanitizeRedirect(input)).toBe(expected)
  })

  it.each([
    'https://evil.example/',
    '//evil.example/path',
    '/\\evil.example',
    '\\\\evil.example',
    'javascript:alert(1)',
    'projects/abc',
    '',
    '/\t/evil.example',
    '/\n/evil.example',
    '/login',
    '/login?redirect=/x',
  ])('отбрасывает %j', (input) => {
    expect(sanitizeRedirect(input)).toBe('/')
  })

  it('отбрасывает не строки', () => {
    expect(sanitizeRedirect(undefined)).toBe('/')
    expect(sanitizeRedirect(42)).toBe('/')
    expect(sanitizeRedirect(['/a'])).toBe('/')
  })
})

describe('loginSearch', () => {
  it('сохраняет адрес возврата', () => {
    expect(loginSearch('/projects/1?x=2')).toEqual({ redirect: '/projects/1?x=2' })
  })

  it('для главной и небезопасных адресов параметр не нужен', () => {
    expect(loginSearch('/')).toEqual({})
    expect(loginSearch('//evil.example')).toEqual({})
  })
})

describe('needsLogin', () => {
  it('нужен вход только гостю при включённых аккаунтах', () => {
    expect(needsLogin({ auth_enabled: true, user: null })).toBe(true)
    expect(needsLogin({ auth_enabled: true, user: { id: '1', email: 'a@b.ru' } })).toBe(false)
    expect(needsLogin({ auth_enabled: false, user: null })).toBe(false)
  })
})

describe('authFormError', () => {
  it('неверные данные входа — под паролем', () => {
    const error = new ApiError(400, 'x', { code: 'LOGIN_BAD_CREDENTIALS' })
    expect(authFormError(error, 'login')).toEqual({
      field: 'password',
      message: 'Неверная почта или пароль',
    })
  })

  it('почта уже занята — под почтой', () => {
    const error = new ApiError(400, 'x', { code: 'REGISTER_USER_ALREADY_EXISTS' })
    expect(authFormError(error, 'register').field).toBe('email')
  })

  it('слабый пароль — под паролем, с правилом', () => {
    const error = new ApiError(400, 'x', { code: 'REGISTER_INVALID_PASSWORD' })
    const result = authFormError(error, 'register')
    expect(result.field).toBe('password')
    expect(result.message).toContain('12')
  })

  it('422 по полю email и password', () => {
    const email = new ApiError(422, 'x', { detail: [{ loc: ['body', 'email'], msg: 'bad' }] })
    const password = new ApiError(422, 'x', { detail: [{ loc: ['body', 'password'], msg: 'bad' }] })
    expect(authFormError(email, 'register').field).toBe('email')
    expect(authFormError(password, 'register').field).toBe('password')
  })

  it('422 по username при входе — тоже почта', () => {
    const error = new ApiError(422, 'x', { detail: [{ loc: ['body', 'username'], msg: 'bad' }] })
    expect(authFormError(error, 'login').field).toBe('email')
  })

  it('слишком частые попытки — общее спокойное сообщение', () => {
    const result = authFormError(new ApiError(429, 'x', { retryAfter: 30 }), 'login')
    expect(result.field).toBe('form')
    expect(result.message).toContain('Подождите')
  })

  it('нет связи и неизвестная ошибка — общие, без технических слов', () => {
    expect(authFormError(new TypeError('network'), 'login').message).toContain('связи')
    const unknown = authFormError(new Error('boom'), 'login')
    expect(unknown.field).toBe('form')
    expect(unknown.message).not.toMatch(/boom|CSRF|backend/i)
  })
})

describe('validateAuthForm', () => {
  it('вход: пустые поля', () => {
    expect(validateAuthForm('login', { email: ' ', password: '' })).toEqual({
      email: 'Укажите почту',
      password: 'Введите пароль',
    })
  })

  it('вход не проверяет длину пароля — её знает сервер', () => {
    expect(validateAuthForm('login', { email: 'a@b.ru', password: '1' })).toEqual({})
  })

  it('регистрация: короткий пароль и кривая почта', () => {
    const errors = validateAuthForm('register', { email: 'not-an-email', password: 'short' })
    expect(errors.email).toBe('Проверьте адрес почты')
    expect(errors.password).toContain('12')
  })

  it('регистрация: корректные данные', () => {
    expect(
      validateAuthForm('register', { email: 'anna@company.ru', password: '123456789012' }),
    ).toEqual({})
  })
})

describe('emailInitialsName', () => {
  it('делит имя из почты на слова для инициалов', () => {
    expect(emailInitialsName('anna.petrova@mail.ru')).toBe('anna petrova')
    expect(emailInitialsName('ivan@mail.ru')).toBe('ivan')
  })
})
