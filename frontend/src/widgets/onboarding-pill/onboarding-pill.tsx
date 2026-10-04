import { useMatch } from '@tanstack/react-router'
import { AnimatePresence, m } from 'motion/react'
import { useEffect, useState } from 'react'
import { CHECKLIST_TOTAL, useChecklistView, useOnboardingUi } from '@/entities/onboarding'
import { useTourStore } from '@/features/onboarding/tour/store'
import { cn } from '@/shared/lib/cn'
import { Button, ProgressRing } from '@/shared/ui'

/** Пауза после финала тура: плашка не должна появиться поверх поздравления. */
export const PILL_DELAY_AFTER_TOUR_MS = 1000

export interface OnboardingPillViewProps {
  done: number
  total?: number
  onClick: () => void
  className?: string
}

/** Сама кнопка плашки: «Начало работы» и счётчик с кольцом прогресса. Без позиции на экране. */
export function OnboardingPillView({
  done,
  total = CHECKLIST_TOTAL,
  onClick,
  className,
}: OnboardingPillViewProps) {
  return (
    <Button
      variant="secondary"
      size="md"
      onClick={onClick}
      aria-label={`Начало работы, выполнено ${done} из ${total}`}
      className={cn('gap-2.5 rounded-full pr-3.5 pl-3 shadow-md', className)}
    >
      <ProgressRing value={done} max={total} size={18} />
      <span>Начало работы</span>
      <span aria-hidden="true" className="h-3.5 w-px bg-border" />
      <span className="text-fg-muted" data-numeric>
        {done}/{total}
      </span>
    </Button>
  )
}

/** Есть ли на экране открытое окно или панель (они закрывают плашку). */
function useDialogOpen(): boolean {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    const check = () =>
      setOpen(document.querySelector('[role="dialog"], [role="alertdialog"]') !== null)
    check()
    // Окна Radix выводятся порталом прямо в body: достаточно следить за его прямыми детьми.
    const observer = new MutationObserver(check)
    observer.observe(document.body, { childList: true })
    return () => observer.disconnect()
  }, [])
  return open
}

/** Подождать после конца тура: `true`, когда плашке уже можно появляться. */
function useSettledAfterTour(tourActive: boolean): boolean {
  const [settled, setSettled] = useState(true)
  const [wasActive, setWasActive] = useState(false)
  useEffect(() => {
    if (tourActive) {
      setWasActive(true)
      setSettled(false)
      return
    }
    if (!wasActive) return
    const timer = window.setTimeout(() => {
      setSettled(true)
      setWasActive(false)
    }, PILL_DELAY_AFTER_TOUR_MS)
    return () => window.clearTimeout(timer)
  }, [tourActive, wasActive])
  return settled
}

/**
 * Плашка прогресса внизу слева. Только на экране проектов: в рабочем месте она закрыла бы зону
 * перетаскивания документов под панелью «Источники», а прогресс там виден в меню аккаунта.
 * Видна, пока онбординг включён, тур не идёт, чек-лист не скрыт и не завершён, нет окна и панели.
 */
export function OnboardingPill() {
  const onHome = useMatch({ from: '/_app/', shouldThrow: false })
  const onProjects = useMatch({ from: '/_app/projects/', shouldThrow: false })
  if (!onHome && !onProjects) return null
  return <PillOnProjects />
}

function PillOnProjects() {
  const view = useChecklistView()
  const panelOpen = useOnboardingUi((state) => state.checklistOpen)
  const openChecklist = useOnboardingUi((state) => state.openChecklist)
  const tourRunning = useTourStore((state) => state.status === 'active')
  const dialogOpen = useDialogOpen()
  const settled = useSettledAfterTour(view.tourActive || tourRunning)
  const visible =
    view.enabled &&
    !view.hidden &&
    !view.complete &&
    !view.tourActive &&
    !tourRunning &&
    settled &&
    !panelOpen &&
    !dialogOpen
  return (
    <AnimatePresence>
      {visible && (
        <m.div
          key="onboarding-pill"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 8 }}
          transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
          className="fixed bottom-5 left-5 z-20"
        >
          <OnboardingPillView done={view.done} onClick={openChecklist} />
        </m.div>
      )}
    </AnimatePresence>
  )
}
