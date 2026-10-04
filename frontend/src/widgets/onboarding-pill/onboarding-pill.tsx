import { useMatch } from '@tanstack/react-router'
import { lazy, Suspense } from 'react'
import { CHECKLIST_TOTAL, useChecklistView } from '@/entities/onboarding'
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

const LazyPill = lazy(() => import('./pill-on-projects'))

/**
 * Плашка прогресса внизу слева. Только на экране проектов: в рабочем месте она закрыла бы зону
 * перетаскивания документов под панелью «Источники», а прогресс там виден в меню аккаунта.
 * Видна, пока онбординг включён, тур не идёт, чек-лист не скрыт и не завершён, нет окна и панели.
 * Код плашки (с анимацией) грузится, только когда она может понадобиться.
 */
export function OnboardingPill() {
  const onHome = useMatch({ from: '/_app/', shouldThrow: false })
  const onProjects = useMatch({ from: '/_app/projects/', shouldThrow: false })
  const view = useChecklistView()
  if (!onHome && !onProjects) return null
  if (!view.enabled || view.hidden || view.complete) return null
  return (
    <Suspense fallback={null}>
      <LazyPill />
    </Suspense>
  )
}
