import { randomUUID } from 'node:crypto'
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname } from 'node:path'
import { type APIRequestContext, type FullConfig, request } from '@playwright/test'
import { AUTH_STATE } from './auth-state'

/**
 * Тестовый пользователь «уже знаком с продуктом»: тур отклонён, чек-лист скрыт. Иначе
 * приветствие и плашка «Начало работы» перекрывали бы сценарии и скриншоты. Если онбординг
 * на стенде выключен (`ONBOARDING_ENABLED=false`), делать нечего.
 */
async function silenceOnboarding(context: APIRequestContext, headers: Record<string, string>) {
  const state = await (await context.get('/api/v1/me/onboarding')).json()
  if (!state.enabled) return
  const dismissed = await context.patch('/api/v1/me/onboarding/tour', {
    data: { status: 'dismissed' },
    headers,
  })
  if (!dismissed.ok())
    throw new Error(`Отказ от обучения тестового пользователя: ${dismissed.status()}`)
  const hidden = await context.patch('/api/v1/me/onboarding/checklist', {
    data: { hidden: true },
    headers,
  })
  if (!hidden.ok()) throw new Error(`Скрытие чек-листа тестового пользователя: ${hidden.status()}`)
}

/**
 * Перед прогоном: если на стенде включены аккаунты, регистрируем одноразового пользователя,
 * входим и сохраняем cookie в `e2e/.auth/state.json` — все сценарии идут уже вошедшими.
 * Без аккаунтов сохраняется пустое состояние.
 */
export default async function globalSetup(config: FullConfig) {
  const baseURL =
    config.projects[0]?.use.baseURL ?? process.env.E2E_BASE_URL ?? 'http://localhost:8080'
  mkdirSync(dirname(AUTH_STATE), { recursive: true })
  const context = await request.newContext({ baseURL })
  try {
    const session = await (await context.get('/api/v1/auth/session')).json()
    if (!session.auth_enabled) {
      writeFileSync(AUTH_STATE, JSON.stringify({ cookies: [], origins: [] }))
      return
    }
    const email = `e2e-${randomUUID()}@example.com`
    const password = `e2e-${randomUUID()}`
    const { csrf_token: csrf } = await (await context.get('/api/v1/auth/csrf')).json()
    const headers = { 'X-CSRF-Token': csrf }
    const registered = await context.post('/api/v1/auth/register', {
      data: { email, password },
      headers,
    })
    if (!registered.ok())
      throw new Error(`Регистрация тестового пользователя: ${registered.status()}`)
    const loggedIn = await context.post('/api/v1/auth/session/login', {
      form: { username: email, password },
      headers,
    })
    if (!loggedIn.ok()) throw new Error(`Вход тестового пользователя: ${loggedIn.status()}`)
    await silenceOnboarding(context, headers)
    await context.storageState({ path: AUTH_STATE })
  } finally {
    await context.dispose()
  }
}
