import { ApiError, RATE_LIMIT_MESSAGE, type Schemas } from '@/shared/api/client'

export type Session = Schemas['SessionState']
export type SessionUser = Schemas['UserRead']

/** Минимальная длина пароля — как на сервере. */
export const PASSWORD_MIN_LENGTH = 8

/** Нужно ли войти: аккаунты включены, а текущий посетитель — гость. */
export function needsLogin(session: Pick<Session, 'auth_enabled' | 'user'>): boolean {
  return session.auth_enabled && !session.user
}

/** Адрес для возврата после входа: только путь этого же сайта; всё остальное — главная. */
export function sanitizeRedirect(value: unknown): string {
  if (typeof value !== 'string') return '/'
  if (!value.startsWith('/') || value.startsWith('//') || value.includes('\\')) return '/'
  // Управляющие символы (перевод строки, табуляция) браузеры вырезают из адреса — так
  // `/\t/evil.com` превращается в `//evil.com`.
  for (const char of value) {
    if (char.charCodeAt(0) <= 0x1f || char.charCodeAt(0) === 0x7f) return '/'
  }
  // Возврат на сам экран входа бессмыслен и даёт петлю.
  if (/^\/login(?:[/?#]|$)/.test(value)) return '/'
  return value
}

/** Параметры адреса `/login`: куда вернуть после входа (главную не пишем). */
export function loginSearch(href: string): { redirect?: string } {
  const redirect = sanitizeRedirect(href)
  return redirect === '/' ? {} : { redirect }
}

/** Инициалы для аватара по почте: «anna.petrova@mail.ru» -> «AP», «ivan@mail.ru» -> «I». */
export function emailInitialsName(email: string): string {
  const local = email.split('@')[0] ?? ''
  return local.replace(/[._\-+]+/g, ' ').trim() || email
}

export type AuthMode = 'login' | 'register'

export interface AuthFormError {
  /** Поле, под которым показать ошибку; form — общая (тост). */
  field: 'email' | 'password' | 'form'
  message: string
}

const PASSWORD_RULE = `Пароль — от ${PASSWORD_MIN_LENGTH} символов`

/** Ошибка входа или регистрации -> текст по-русски и место на экране. */
export function authFormError(error: unknown, mode: AuthMode): AuthFormError {
  if (error instanceof ApiError) {
    if (error.status === 429) return { field: 'form', message: RATE_LIMIT_MESSAGE }
    if (error.code === 'LOGIN_BAD_CREDENTIALS') {
      return { field: 'password', message: 'Неверная почта или пароль' }
    }
    if (error.code === 'REGISTER_USER_ALREADY_EXISTS') {
      return { field: 'email', message: 'Эта почта уже зарегистрирована. Войдите в аккаунт' }
    }
    if (error.code === 'REGISTER_INVALID_PASSWORD') {
      return { field: 'password', message: `Пароль не подходит. ${PASSWORD_RULE}` }
    }
    if (error.status === 422) return validationError(error.detail, mode)
  }
  if (error instanceof TypeError) {
    return { field: 'form', message: 'Нет связи с сервером. Проверьте подключение' }
  }
  return { field: 'form', message: 'Не удалось выполнить запрос. Повторите попытку' }
}

/** Ошибки проверки полей (422): ищем, какое поле не принято. */
function validationError(detail: unknown, mode: AuthMode): AuthFormError {
  const fields = Array.isArray(detail)
    ? detail.flatMap((item: { loc?: unknown[] }) => (Array.isArray(item?.loc) ? item.loc : []))
    : []
  if (fields.includes('email') || (mode === 'login' && fields.includes('username'))) {
    return { field: 'email', message: 'Проверьте адрес почты' }
  }
  if (fields.includes('password')) {
    return { field: 'password', message: PASSWORD_RULE }
  }
  return { field: 'form', message: 'Проверьте введённые данные' }
}

/** Проверка формы до отправки. */
export function validateAuthForm(
  mode: AuthMode,
  values: { email: string; password: string },
): { email?: string; password?: string } {
  const errors: { email?: string; password?: string } = {}
  const email = values.email.trim()
  if (!email) errors.email = 'Укажите почту'
  else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) errors.email = 'Проверьте адрес почты'
  if (!values.password) errors.password = 'Введите пароль'
  else if (mode === 'register' && values.password.length < PASSWORD_MIN_LENGTH) {
    errors.password = PASSWORD_RULE
  }
  return errors
}
