import type { ReactNode } from 'react'
import { cn } from '@/shared/lib/cn'
import { FlowLine, type FlowLineState } from '../flow-line/flow-line'
import { Icon } from '../icon'

export type StepStatus = 'complete' | 'current' | 'upcoming' | 'error'

export interface StepItem {
  id: string
  title: ReactNode
  /** Деталь этапа: «Найдено 4 вопроса», текст ошибки. */
  description?: ReactNode
  /** Справа: длительность, время. */
  meta?: ReactNode
  status: StepStatus
}

const STATUS_TEXT: Record<StepStatus, string> = {
  complete: 'готово',
  current: 'выполняется',
  upcoming: 'ожидает',
  error: 'ошибка',
}

function connector(from: StepStatus, to: StepStatus): FlowLineState {
  if (from === 'complete' && to === 'current') return 'active'
  if (from === 'complete' && (to === 'complete' || to === 'error')) return 'done'
  return 'idle'
}

function Indicator({ status }: { status: StepStatus }) {
  if (status === 'complete') {
    return (
      <span className="grid size-5 place-items-center rounded-full bg-accent-subtle text-accent-fg ring-1 ring-accent/30">
        <Icon name="check" size={14} />
      </span>
    )
  }
  if (status === 'error') {
    return (
      <span className="grid size-5 place-items-center rounded-full bg-danger-subtle text-danger-fg ring-1 ring-danger/35">
        <Icon name="x" size={14} />
      </span>
    )
  }
  if (status === 'current') {
    return (
      <span className="relative grid size-5 place-items-center rounded-full bg-surface ring-1 ring-accent">
        <span className="absolute inset-0 animate-breathe rounded-full bg-accent/25 motion-reduce:hidden" />
        <span className="size-2 rounded-full bg-accent" />
      </span>
    )
  }
  return (
    <span className="grid size-5 place-items-center rounded-full bg-surface ring-1 ring-border-strong">
      <span className="size-1.5 rounded-full bg-border-strong" />
    </span>
  )
}

export interface StepperProps {
  steps: StepItem[]
  /** Подпись списка этапов для скринридера: «Ход прогона». */
  'aria-label': string
  className?: string
}

/** Вертикальный ход этапов: прогон модели, импорт документа. Текущий этап связан линией тока. */
export function Stepper({ steps, className, 'aria-label': ariaLabel }: StepperProps) {
  return (
    <ol aria-label={ariaLabel} className={cn('flex flex-col', className)}>
      {steps.map((step, index) => {
        const next = steps[index + 1]
        return (
          <li
            key={step.id}
            aria-current={step.status === 'current' ? 'step' : undefined}
            className="relative flex gap-3 pb-5 last:pb-0"
          >
            {next && (
              <FlowLine
                orientation="vertical"
                state={connector(step.status, next.status)}
                className="absolute top-6 bottom-1 left-2.5 -translate-x-1/2"
              />
            )}
            <div className="relative z-10 flex h-5 shrink-0 items-center">
              <Indicator status={step.status} />
            </div>
            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
              <div className="flex items-baseline justify-between gap-3">
                <span
                  className={cn(
                    'text-sm font-medium transition-colors duration-slow',
                    step.status === 'upcoming' && 'text-fg-subtle',
                    step.status === 'complete' && 'text-fg-muted',
                    step.status === 'current' && 'text-fg',
                    step.status === 'error' && 'text-danger-fg',
                  )}
                >
                  {step.title}
                  <span className="sr-only">, {STATUS_TEXT[step.status]}</span>
                </span>
                {step.meta && (
                  <span data-numeric className="shrink-0 type-caption text-fg-subtle">
                    {step.meta}
                  </span>
                )}
              </div>
              {step.description && (
                <div className="type-caption text-fg-muted">{step.description}</div>
              )}
            </div>
          </li>
        )
      })}
    </ol>
  )
}
