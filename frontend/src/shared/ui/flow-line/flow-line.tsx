import { cn } from '@/shared/lib/cn'

export type FlowLineState = 'idle' | 'active' | 'done'

export interface FlowLineProps {
  orientation?: 'horizontal' | 'vertical'
  /** idle — путь впереди; active — по линии идёт ток (процесс выполняется); done — пройдено. */
  state?: FlowLineState
  className?: string
}

/**
 * Фирменный приём «Линия тока»: тонкая линия хода процесса. В активном состоянии по ней
 * спокойно бежит импульс акцентного цвета. При сокращённом движении — статичная заливка.
 * Размер вдоль оси задаёт родитель (h-full / w-full или абсолютное позиционирование).
 */
export function FlowLine({ orientation = 'horizontal', state = 'idle', className }: FlowLineProps) {
  const vertical = orientation === 'vertical'
  return (
    <span
      aria-hidden="true"
      data-state={state}
      className={cn(
        'relative block overflow-hidden rounded-full transition-colors duration-(--duration-slow) ease-soft',
        vertical ? 'w-px' : 'h-px',
        state === 'done' ? 'bg-accent/45' : 'bg-border-strong',
        state === 'active' && 'motion-reduce:bg-accent/45',
        className,
      )}
    >
      {state === 'active' && (
        <span
          className={cn(
            'absolute from-transparent via-accent to-transparent motion-reduce:hidden',
            vertical
              ? 'inset-x-0 top-0 h-2/5 animate-flow-y bg-linear-to-b'
              : 'inset-y-0 left-0 w-2/5 animate-flow bg-linear-to-r',
          )}
        />
      )}
    </span>
  )
}
