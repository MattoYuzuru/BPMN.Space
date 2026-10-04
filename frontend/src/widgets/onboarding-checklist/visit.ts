import { useNavigate } from '@tanstack/react-router'
import { useCallback, useState } from 'react'
import {
  type ChecklistItemKey,
  checklistItemTitle,
  fetchItemTarget,
  useOnboardingUi,
} from '@/entities/onboarding'
import { showHint } from '@/features/onboarding/hint'
import { errorMessage } from '@/shared/api/client'
import { toast } from '@/shared/ui'
import { useWorkspaceUi } from '@/widgets/workspace/model'
import { setActiveHintItem } from './active-hint'
import { type ItemVisit, planItemVisit } from './target'

/** Подготовка экрана перед подсказкой: развернуть панель, показать вопрос на схеме (`?question=` выбирает его сам). */
export function prepareVisit(visit: ItemVisit): () => void {
  return () => {
    const ui = useWorkspaceUi.getState()
    if (visit.expand) ui.expandPanel(visit.expand)
    if (visit.focusQuestionId) ui.focusQuestion(visit.focusQuestionId)
  }
}

type Navigate = (visit: ItemVisit['destination']) => Promise<unknown>

/** Показать подсказку-указатель по плану (переход уже выполнен). */
export function presentVisit(item: ChecklistItemKey, visit: ItemVisit): void {
  showHint({ anchor: visit.anchor, text: visit.text, prepare: prepareVisit(visit) })
  setActiveHintItem(item)
}

/** Перейти по плану и показать подсказку. */
export async function performVisit(
  item: ChecklistItemKey,
  visit: ItemVisit,
  navigate: Navigate,
): Promise<void> {
  await navigate(visit.destination)
  presentVisit(item, visit)
}

/**
 * Переход к невыполненному пункту: спрашиваем сервер, куда вести; закрываем панель; идём на
 * экран; показываем подсказку-указатель. Пока идёт запрос, `pending` — ключ пункта.
 */
export function useVisitItem() {
  const navigate = useNavigate()
  const [pending, setPending] = useState<ChecklistItemKey | null>(null)

  const go: Navigate = useCallback(
    async (destination) => {
      if (destination.to === '/') return navigate({ to: '/' })
      return navigate({
        to: '/projects/$projectId',
        params: { projectId: destination.projectId },
        search: destination.question ? { question: destination.question } : undefined,
      })
    },
    [navigate],
  )

  const visit = useCallback(
    async (item: ChecklistItemKey) => {
      setPending(item)
      try {
        const target = await fetchItemTarget(item)
        useOnboardingUi.getState().closeChecklist()
        await performVisit(item, planItemVisit(item, target), go)
      } catch (error) {
        toast.error(`Не удалось открыть «${checklistItemTitle(item)}»`, {
          description: errorMessage(error),
        })
      } finally {
        setPending(null)
      }
    },
    [go],
  )

  return { visit, pending }
}
