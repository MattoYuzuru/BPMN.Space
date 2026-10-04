import { AnimatePresence, m } from 'motion/react'
import { useEffect, useState } from 'react'
import { useChecklistView, useOnboardingUi } from '@/entities/onboarding'
import { useTourStore } from '@/features/onboarding/tour/store'
import { DURATION, EASE_SOFT } from '@/shared/lib/motion'
import { OnboardingPillView, PILL_DELAY_AFTER_TOUR_MS } from './onboarding-pill'

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

export default function PillOnProjects() {
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
          transition={{ duration: DURATION.base, ease: EASE_SOFT }}
          className="fixed bottom-5 left-5 z-20"
        >
          <OnboardingPillView done={view.done} onClick={openChecklist} />
        </m.div>
      )}
    </AnimatePresence>
  )
}
