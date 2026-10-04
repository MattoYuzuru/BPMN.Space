import { lazy, Suspense, useState } from 'react'
import { useChecklistView, useOnboardingUi } from '@/entities/onboarding'
import { HintHost } from '@/features/onboarding/hint'
import { OnboardingPill } from '@/widgets/onboarding-pill/onboarding-pill'
import { OnboardingWatcher } from './onboarding-watcher'

const ChecklistSheet = lazy(() => import('./checklist-sheet'))

/**
 * Слой чек-листа «Начало работы» в закрытом разделе: следит за прогрессом (уведомления),
 * показывает плашку на экране проектов, панель и подсказки-указатели. Панель грузится при первом
 * открытии. Без онбординга (стенд без аккаунтов, флаг выключен) ничего не рисует.
 */
export function OnboardingLayer() {
  const { enabled } = useChecklistView()
  return (
    <>
      <OnboardingWatcher />
      {enabled && (
        <>
          <OnboardingPill />
          <ChecklistPanelHost />
        </>
      )}
      <HintHost />
    </>
  )
}

/** Панель живёт в дереве после первого открытия, чтобы закрытие проигрывалось плавно. */
function ChecklistPanelHost() {
  const open = useOnboardingUi((state) => state.checklistOpen)
  const [everOpened, setEverOpened] = useState(false)
  if (open && !everOpened) setEverOpened(true)
  if (!open && !everOpened) return null
  return (
    <Suspense fallback={null}>
      <ChecklistSheet />
    </Suspense>
  )
}
