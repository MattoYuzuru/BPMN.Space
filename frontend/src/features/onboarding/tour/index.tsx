import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { useTourStore } from './store'
import type { TourHostProps } from './tour-host'

export { createTourController, resolveView } from './machine'
export { startTour, stopTour, useTourStore } from './store'
export type { TourHostProps } from './tour-host'
export type {
  CoachPage,
  RouteTarget,
  SignalMemory,
  StepAction,
  StepView,
  StepViewContext,
  TourApi,
  TourEndReason,
  TourPersistence,
  TourSide,
  TourStatus,
  TourStep,
} from './types'

const LazyTourHost = lazy(() => import('./tour-host'))

/**
 * Хост тура. Чанк с движком грузится только когда тур нужен: `enabled` (сервер говорит, что тур
 * активен — восстановить шаг) или тур уже запущен через `startTour`. Без тура вес приложения не
 * растёт и ни одного наблюдателя (MutationObserver/ResizeObserver) нет.
 */
export function TourHost<Ctx>({
  enabled = false,
  ...props
}: TourHostProps<Ctx> & { enabled?: boolean }) {
  const running = useTourStore((state) => state.status === 'active')
  // После конца тура хост живёт ещё чуть-чуть: затемнение гаснет плавно, а не обрывается.
  const [lingering, setLingering] = useState(false)
  const wasRunning = useRef(false)
  useEffect(() => {
    if (running) {
      wasRunning.current = true
      return
    }
    if (!wasRunning.current) return
    wasRunning.current = false
    setLingering(true)
    const timer = window.setTimeout(() => setLingering(false), 400)
    return () => window.clearTimeout(timer)
  }, [running])
  if (!enabled && !running && !lingering) return null
  const Host = LazyTourHost as unknown as (props: TourHostProps<Ctx>) => React.JSX.Element
  return (
    <Suspense fallback={null}>
      <Host {...props} />
    </Suspense>
  )
}
