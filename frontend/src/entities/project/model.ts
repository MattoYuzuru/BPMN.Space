import type { Schemas } from '@/shared/api/client'
import type { BadgeTone, IconName } from '@/shared/ui'

export type ProjectStatus = Schemas['ProjectStatus']

export const PROJECT_STATUS: Record<
  ProjectStatus,
  { label: string; tone: BadgeTone; icon: IconName }
> = {
  empty: { label: 'Нет источников', tone: 'neutral', icon: 'circle-dashed' },
  analyzing: { label: 'Идёт анализ', tone: 'accent', icon: 'bolt' },
  needs_answers: { label: 'Есть вопросы', tone: 'amber', icon: 'message-question' },
  ready: { label: 'Схема готова', tone: 'success', icon: 'circle-check' },
  building: { label: 'Строится схема', tone: 'accent', icon: 'diagram' },
}

/**
 * Статус для карточки и шапки. Бэкенд считает проект без открытых вопросов «готовым», даже
 * если схему ещё не строили, — тогда честнее сказать «Можно строить».
 */
export function projectStatusView(project: {
  status: ProjectStatus
  counts: { versions: number }
}): { label: string; tone: BadgeTone; icon: IconName } {
  if (project.status === 'ready' && project.counts.versions === 0) {
    return { label: 'Можно строить схему', tone: 'neutral', icon: 'diagram' }
  }
  return PROJECT_STATUS[project.status]
}

/** Идёт ли по проекту прогон (кнопки запуска недоступны, правка схемы — только после). */
export function isRunning(status: ProjectStatus): boolean {
  return status === 'analyzing' || status === 'building'
}

export type ProjectAccess = Schemas['ProjectRole']

/** Что можно делать в проекте. Экраны получают готовые флаги и сами роль не сравнивают. */
export interface ProjectCapabilities {
  /** Менять содержимое: источники, вопросы, схему, запуск прогонов, название. */
  canEdit: boolean
  /** Удалять проект и управлять доступом (владелец). */
  canManage: boolean
  /** Делиться проектом: владелец и только при включённых аккаунтах (ссылки хранятся в Postgres). */
  canShare: boolean
}

/**
 * Возможности по роли: viewer только читает, editor правит всё, кроме удаления и доступа.
 * Без аккаунтов (`authEnabled: false`) сервер считает всех владельцами, но делиться нечем:
 * ссылки и участники живут в аккаунтах, поэтому `canShare` там всегда ложь.
 */
export function projectCapabilities(
  access: ProjectAccess,
  authEnabled: boolean,
): ProjectCapabilities {
  const canManage = access === 'owner'
  return { canEdit: access !== 'viewer', canManage, canShare: canManage && authEnabled }
}

/** Проект открыт только для чтения (демо-примеры, ссылка «только просмотр»). */
export function isReadOnly(access: ProjectAccess): boolean {
  return !projectCapabilities(access, false).canEdit
}

export type ProjectScope = Schemas['ProjectScope']

/** Области списка проектов: подпись для переключателя и пустого состояния. */
export const PROJECT_SCOPES: { value: ProjectScope; label: string }[] = [
  { value: 'all', label: 'Все' },
  { value: 'own', label: 'Мои' },
  { value: 'shared', label: 'Общие' },
  { value: 'examples', label: 'Примеры' },
]

/** Область из адреса: незнакомое значение и «все» — это область по умолчанию. */
export function scopeFromSearch(value: unknown): ProjectScope {
  const known = PROJECT_SCOPES.find((scope) => scope.value === value)
  return known ? known.value : 'all'
}

/** Область для адреса: по умолчанию («все») параметр не пишем. */
export function scopeToSearch(scope: ProjectScope): Exclude<ProjectScope, 'all'> | undefined {
  return scope === 'all' ? undefined : scope
}
