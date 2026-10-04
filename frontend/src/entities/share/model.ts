import { ApiError, type Schemas } from '@/shared/api/client'
import type { IconName } from '@/shared/ui'

export type ShareRole = Schemas['ShareRole']
export type ShareLink = Schemas['ShareLinkRead']
export type ShareLinkCreated = Schemas['ShareLinkCreated']
export type ProjectMember = Schemas['ProjectMemberRead']
export type SharedProject = Schemas['SharedProject']

/** Роль в ссылке: подпись и значок. «Просмотр» — только чтение, «Редактирование» — приглашение. */
export const SHARE_ROLE: Record<ShareRole, { label: string; icon: IconName }> = {
  viewer: { label: 'Просмотр', icon: 'eye' },
  editor: { label: 'Редактирование', icon: 'pencil' },
}

export const SHARE_ROLES: ShareRole[] = ['viewer', 'editor']

export interface ExpiryOption {
  /** Число дней строкой — так его отдаёт Select. */
  value: string
  label: string
}

/**
 * Одинаковые сроки для просмотра и редактирования: 7 дней, 30 дней, год или бессрочно.
 */
const EXPIRY = [
  { days: 7, label: '7 дней' },
  { days: 30, label: '30 дней' },
  { days: 365, label: 'Год' },
  { days: 0, label: 'Бессрочно' },
]

const DEFAULT_EXPIRY = 30

export function expiryOptions(role: ShareRole): ExpiryOption[] {
  void role
  return EXPIRY.map(({ days, label }) => ({ value: String(days), label }))
}

export function defaultExpiryDays(role: ShareRole): number {
  void role
  return DEFAULT_EXPIRY
}

/** При смене роли срок сохраняется, если он допустим для новой роли; иначе — срок по умолчанию. */
export function expiryForRole(role: ShareRole, days: number): number {
  void role
  return EXPIRY.some((option) => option.days === days) ? days : DEFAULT_EXPIRY
}

/** Полный адрес ссылки: путь с секретом приходит от сервера один раз. */
export function shareUrl(origin: string, urlPath: string): string {
  return `${origin.replace(/\/$/, '')}${urlPath}`
}

export type LinkState = 'active' | 'expired' | 'revoked'

export function linkState(link: ShareLink, now: Date = new Date()): LinkState {
  if (link.revoked_at) return 'revoked'
  if (link.expires_at && new Date(link.expires_at).getTime() <= now.getTime()) return 'expired'
  return 'active'
}

/** Действующие ссылки, новые первыми; отозванные и истёкшие в диалоге не показываем. */
export function activeLinks(links: readonly ShareLink[], now: Date = new Date()): ShareLink[] {
  return links
    .filter((link) => linkState(link, now) === 'active')
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
}

/** Состояние публичной страницы `/share/<токен>`. */
export type SharePageState =
  | { kind: 'loading' }
  /** Ссылка на просмотр: проект открыт только для чтения. */
  | { kind: 'viewer'; shared: SharedProject }
  /** Приглашение редактора, посетитель вошёл: можно принять. */
  | { kind: 'invite'; shared: SharedProject }
  /** Приглашение редактора, посетитель гость: сначала войти. */
  | { kind: 'sign-in' }
  /** Ссылка неизвестна или отозвана. */
  | { kind: 'invalid' }
  /** Срок ссылки вышел. */
  | { kind: 'expired' }
  | { kind: 'failed'; error: unknown }

/** Ответ сервера по ссылке -> экран. Единственное место, где коды ответа становятся состояниями. */
export function sharePageState(result: {
  status: 'pending' | 'error' | 'success'
  data?: SharedProject
  error?: unknown
}): SharePageState {
  if (result.status === 'pending') return { kind: 'loading' }
  if (result.status === 'error') {
    const error = result.error
    if (error instanceof ApiError) {
      if (error.status === 404) return { kind: 'invalid' }
      if (error.status === 410) return { kind: 'expired' }
      if (error.status === 401) return { kind: 'sign-in' }
    }
    return { kind: 'failed', error }
  }
  const shared = result.data as SharedProject
  return shared.role === 'editor' ? { kind: 'invite', shared } : { kind: 'viewer', shared }
}
