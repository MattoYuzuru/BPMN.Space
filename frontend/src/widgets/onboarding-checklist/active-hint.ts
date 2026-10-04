import type { ChecklistItemKey } from '@/entities/onboarding'
import { hideHint } from '@/features/onboarding/hint'

/** Пункт, на который сейчас указывает подсказка: когда он выполнен, подсказка закрывается сама. */
let hintItem: ChecklistItemKey | null = null

/** Запомнить пункт показанной подсказки. */
export function setActiveHintItem(item: ChecklistItemKey | null): void {
  hintItem = item
}

/** Закрыть подсказку, если она про один из только что выполненных пунктов. */
export function dismissHintFor(done: readonly ChecklistItemKey[]): void {
  if (hintItem && done.includes(hintItem)) {
    hintItem = null
    hideHint()
  }
}
