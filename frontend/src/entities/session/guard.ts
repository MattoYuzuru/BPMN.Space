import type { QueryClient } from '@tanstack/react-query'
import { redirect } from '@tanstack/react-router'
import { sessionQueryOptions } from './api'
import { loginSearch, needsLogin, type Session, sanitizeRedirect } from './model'

/**
 * Охрана закрытых экранов (`beforeLoad` защищённого раздела). Гостя при включённых аккаунтах
 * отправляет на вход с адресом возврата; без аккаунтов или со входом — пропускает.
 * Публичные маршруты (вход, стайлгайд, ссылки «поделиться») охрану не подключают.
 */
export async function requireSession(client: QueryClient, href: string): Promise<Session> {
  const session = await client.ensureQueryData(sessionQueryOptions)
  if (needsLogin(session)) throw redirect({ to: '/login', search: loginSearch(href) })
  return session
}

/**
 * Экран входа нужен только гостю: при выключенных аккаунтах и после входа он ведёт дальше —
 * на адрес возврата или главную.
 */
export async function skipLoginIfSignedIn(
  client: QueryClient,
  target: string | undefined,
): Promise<void> {
  const session = await client.ensureQueryData(sessionQueryOptions)
  if (!needsLogin(session)) throw redirect({ href: sanitizeRedirect(target) })
}
