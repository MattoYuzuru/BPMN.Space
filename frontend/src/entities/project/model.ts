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

/** Идёт ли по проекту прогон (кнопки запуска недоступны, правка схемы — только после). */
export function isRunning(status: ProjectStatus): boolean {
  return status === 'analyzing' || status === 'building'
}
