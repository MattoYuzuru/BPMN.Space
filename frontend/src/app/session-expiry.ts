import type { QueryClient } from '@tanstack/react-query'
import {
  dropAccountData,
  loginSearch,
  needsLogin,
  type Session,
  sessionQueryOptions,
} from '@/entities/session'

export interface SessionExpiryContext {
  client: QueryClient
  /** Закрытый ли экран открыт: на публичных (вход, стайлгайд) 401 ни к чему не ведёт. */
  isProtected: () => boolean
  /** Адрес, на котором застала ошибка, — вернёмся на него после входа. */
  currentHref: () => string
  toLogin: (search: { redirect?: string }) => Promise<unknown>
}

let pending: Promise<void> | undefined

/**
 * Сервер ответил 401: сессия закончилась. Перечитываем состояние входа и, если мы действительно
 * гости, уводим на экран входа с возвратом на текущий адрес. Параллельные 401 обрабатываются один раз.
 */
export function handleUnauthorized(context: SessionExpiryContext): Promise<void> {
  if (!context.isProtected()) return Promise.resolve()
  pending ??= (async () => {
    const href = context.currentHref()
    const session: Session = await context.client.fetchQuery({
      ...sessionQueryOptions,
      staleTime: 0,
    })
    if (!needsLogin(session)) return
    dropAccountData(context.client)
    await context.toLogin(loginSearch(href))
  })()
    .catch(() => undefined)
    .finally(() => {
      pending = undefined
    })
  return pending
}
