import {
  CHECKLIST_TOTAL,
  type ChecklistItemKey,
  checklistItemTitle,
  useOnboardingUi,
} from '@/entities/onboarding'
import { pluralRu } from '@/shared/lib/format'
import { toast } from '@/shared/ui'

/** Одно уведомление на всё, что отметилось между двумя ответами сервера. */
export function announceProgress(added: readonly ChecklistItemKey[], done: number): void {
  if (added.length === 0) return
  if (done >= CHECKLIST_TOTAL) {
    // Финал: плашка уходит, ссылаться на чек-лист уже незачем.
    toast.success('Вы освоили Архитектор', { id: 'onboarding-progress' })
    return
  }
  const [first] = added
  const title =
    added.length === 1 && first
      ? `Готово: ${checklistItemTitle(first)}`
      : `Готово: ${added.length} ${pluralRu(added.length, ['шаг', 'шага', 'шагов'])}`
  toast.success(title, {
    id: 'onboarding-progress',
    description: `Начало работы — ${done} из ${CHECKLIST_TOTAL}`,
    action: { label: 'Открыть', onClick: () => useOnboardingUi.getState().openChecklist() },
  })
}
