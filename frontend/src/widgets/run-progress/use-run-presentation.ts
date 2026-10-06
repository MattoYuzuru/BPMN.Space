import { useReducedMotion } from 'motion/react'
import { useEffect, useState } from 'react'
import { type RunView, STAGES } from '@/entities/run'

/** Короткая пауза чтения этапа; она не задерживает сервер, кэш или появление схемы. */
export const STAGE_VISIBLE_MS = 300
export const SUMMARY_VISIBLE_MS = 2500

/** Вызывается в компоненте с key=runId: очередь никогда не переходит к другому прогону. */
export function useRunPresentation(view: RunView, needsPresentation: boolean) {
  const reducedMotion = useReducedMotion()
  const stages = STAGES[view.mode]
  const target =
    view.status === 'succeeded' ? stages.length : view.stage ? stages.indexOf(view.stage) : -1
  const [shown, setShown] = useState(() => ({
    index: needsPresentation && view.status === 'succeeded' ? 0 : target,
    at: Date.now(),
  }))
  const successful = view.status === 'running' || view.status === 'succeeded'
  const index = reducedMotion || !needsPresentation ? target : shown.index

  useEffect(() => {
    if (!successful || reducedMotion || !needsPresentation || shown.index >= target) return
    const delay = shown.index < 0 ? 0 : Math.max(0, STAGE_VISIBLE_MS - (Date.now() - shown.at))
    const timer = setTimeout(() => {
      setShown({ index: shown.index + 1, at: Date.now() })
    }, delay)
    return () => clearTimeout(timer)
  }, [target, shown, successful, reducedMotion, needsPresentation])

  const presenting = successful && needsPresentation && index < stages.length
  const displayView: RunView = presenting
    ? { ...view, status: 'running', stage: stages[index] ?? null }
    : view
  return { displayView, presenting, summaryShown: view.status === 'succeeded' && !presenting }
}
