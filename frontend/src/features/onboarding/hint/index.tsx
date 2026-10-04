import { lazy, Suspense } from 'react'
import { useHintStore } from './store'

export type { HintRequest } from './store'
export { hideHint, showHint } from './store'

const LazyHintHost = lazy(() => import('./hint-host'))

/** Хост подсказок-указателей: чанк грузится, только когда подсказку попросили показать. */
export function HintHost() {
  const open = useHintStore((state) => state.current !== null)
  if (!open) return null
  return (
    <Suspense fallback={null}>
      <LazyHintHost />
    </Suspense>
  )
}
