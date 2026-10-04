import { useMemo } from 'react'
import { useOnboarding } from './api'
import type { ChecklistItemKey } from './items'
import { checklistProgress, completedKeys, isTourActive } from './model'

export interface ChecklistView {
  /** Онбординг включён и состояние загружено. */
  enabled: boolean
  done: number
  total: number
  /** Все пункты отмечены. */
  complete: boolean
  /** Плашка скрыта пользователем (уведомления о новых пунктах при этом продолжают приходить). */
  hidden: boolean
  /** Тур идёт на сервере (в том числе на паузе). */
  tourActive: boolean
  doneKeys: ReadonlySet<ChecklistItemKey>
}

/** Прогресс чек-листа «Начало работы» текущего пользователя для меню, плашки и панели. */
export function useChecklistView(): ChecklistView {
  const state = useOnboarding().data
  const progress = checklistProgress(state)
  const doneKeys = useMemo(() => completedKeys(state), [state])
  return {
    enabled: Boolean(state?.enabled && state.checklist),
    done: progress.done,
    total: progress.total,
    complete: progress.complete,
    hidden: Boolean(state?.checklist?.hidden),
    tourActive: isTourActive(state),
    doneKeys,
  }
}
