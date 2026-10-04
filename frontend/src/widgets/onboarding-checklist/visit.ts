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
import { getWorkspaceControls, type WorkspaceControls } from '@/widgets/workspace/model'
import { setActiveHintItem } from './active-hint'
import { type ItemVisit, planItemVisit } from './target'

const WORKSPACE_WAIT_MS = 3000
const WORKSPACE_POLL_MS = 100

/** Рабочее место регистрирует управление после монтирования: дожидаемся его недолго. */
function whenWorkspaceReady(run: (controls: WorkspaceControls) => void): void {
  const startedAt = Date.now()
  const attempt = () => {
    const controls = getWorkspaceControls()
    if (controls) return run(controls)
    if (Date.now() - startedAt < WORKSPACE_WAIT_MS) window.setTimeout(attempt, WORKSPACE_POLL_MS)
  }
  attempt()
}

/** Подготовка экрана перед подсказкой: развернуть панель, выбрать вопрос и показать его на схеме. */
export function prepareVisit(visit: ItemVisit): () => void {
  return () => {
    if (!visit.expand && !visit.focusQuestionId) return
    whenWorkspaceReady((controls) => {
      if (visit.expand) controls.expandPanel(visit.expand)
      if (visit.focusQuestionId) controls.selectQuestion(visit.focusQuestionId, { focus: true })
    })
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
