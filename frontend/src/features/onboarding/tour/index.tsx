import { lazy, Suspense } from 'react'
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
  if (!enabled && !running) return null
  const Host = LazyTourHost as unknown as (props: TourHostProps<Ctx>) => React.JSX.Element
  return (
    <Suspense fallback={null}>
      <Host {...props} />
    </Suspense>
  )
}
