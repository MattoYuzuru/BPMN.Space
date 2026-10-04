import { lazy, Suspense, useEffect, useState } from 'react'
import {
  isTourActive,
  type OnboardingState,
  shouldOfferTour,
  useOnboarding,
  useUpdateTour,
} from '@/entities/onboarding'
import { startTour, useTourStore } from '@/features/onboarding/tour'
import { WELCOME } from '@/features/onboarding/tour/copy'
import { resetTourSession } from '@/features/onboarding/tour/session'
import { WelcomeDialog } from '@/features/onboarding/welcome-dialog'
import { errorMessage } from '@/shared/api/client'
import { toast } from '@/shared/ui'

// Сборка тура (сценарий, тексты, хост) — отдельный чанк: грузится, только когда тур идёт.
const TourRoot = lazy(() => import('./tour-root'))

/** Пауза между отрисовкой экрана и приветствием. */
const WELCOME_DELAY_MS = 400
const OPEN_DIALOG = '[role="dialog"][data-state="open"], [role="alertdialog"][data-state="open"]'

/**
 * Приветствие после первого входа и сборка тура. Весь модуль — ленивый чанк (`OnboardingRoot`
 * подключает его, только когда онбординг включён): тексты, сессия и машина тура не входят в
 * стартовый бандл.
 */
export default function OnboardingGate() {
  const onboarding = useOnboarding()
  const state = onboarding.data
  const localActive = useTourStore((s) => s.status === 'active')
  const wanted = Boolean(state?.enabled) && (isTourActive(state) || localActive)
  // Однажды показанный тур остаётся смонтированным: затемнение гаснет плавно после конца.
  const [mounted, setMounted] = useState(false)
  useEffect(() => {
    if (wanted) setMounted(true)
  }, [wanted])

  if (!state?.enabled) return null
  return (
    <>
      <WelcomeGate state={state} tourRunning={localActive} />
      {(wanted || mounted) && (
        <Suspense fallback={null}>
          <TourRoot state={state} />
        </Suspense>
      )}
    </>
  )
}

/** Приветствие: показывается, когда тур ещё не предлагали, спустя паузу и не поверх другого окна. */
function WelcomeGate({ state, tourRunning }: { state: OnboardingState; tourRunning: boolean }) {
  const offer = shouldOfferTour(state) && !tourRunning
  const [ready, setReady] = useState(false)
  const [choice, setChoice] = useState<'start' | 'skip' | null>(null)
  const update = useUpdateTour()

  useEffect(() => {
    if (!offer) {
      setReady(false)
      return
    }
    const begin = Date.now()
    let timer = 0
    const check = () => {
      // Другое окно открыто — ждём, пока закроется.
      if (document.querySelector(OPEN_DIALOG) || Date.now() - begin < WELCOME_DELAY_MS) {
        timer = window.setTimeout(check, 200)
        return
      }
      setReady(true)
    }
    timer = window.setTimeout(check, WELCOME_DELAY_MS)
    return () => window.clearTimeout(timer)
  }, [offer])

  const start = () => {
    setChoice('start')
    resetTourSession()
    update
      .mutateAsync({ status: 'active', step: 'project.create' })
      .then(() => startTour('project.create'))
      .catch((error) => {
        setChoice(null)
        toast.error('Не удалось начать обучение', { description: errorMessage(error) })
      })
  }

  const skip = () => {
    setChoice('skip')
    update.mutate(
      { status: 'dismissed' },
      {
        onSuccess: () => toast(WELCOME.skipToast),
        onError: () => setChoice(null),
      },
    )
  }

  return (
    <WelcomeDialog
      open={offer && ready && choice !== 'skip'}
      pending={choice === 'start'}
      onStart={start}
      onSkip={skip}
    />
  )
}
