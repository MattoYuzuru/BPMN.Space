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
