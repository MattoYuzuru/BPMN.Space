import type { ChecklistItemKey } from '@/entities/onboarding'
import { hideHint } from '@/features/onboarding/hint'
import { useHintStore } from '@/features/onboarding/hint/store'

/** Пункт показанной подсказки и её номер: чужую (позднюю) подсказку закрывать нельзя. */
let active: { item: ChecklistItemKey; id: number | undefined } | null = null

/** Запомнить пункт только что показанной подсказки (вызывать сразу после `showHint`). */
export function setActiveHintItem(item: ChecklistItemKey | null): void {
  active = item ? { item, id: useHintStore.getState().current?.id } : null
}

/** Закрыть подсказку, если она про один из только что выполненных пунктов и всё ещё та же. */
export function dismissHintFor(done: readonly ChecklistItemKey[]): void {
  if (!active || !done.includes(active.item)) return
  const { id } = active
  active = null
  if (useHintStore.getState().current?.id === id) hideHint()
}
