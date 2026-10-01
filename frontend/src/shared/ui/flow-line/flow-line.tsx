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
 * спокойно бежит импульс акцентного цвета с мягким ореолом. При сокращённом движении —
 * статичная заливка. Размер вдоль оси задаёт родитель (flex-1, h-full или absolute).
 */
export function FlowLine({ orientation = 'horizontal', state = 'idle', className }: FlowLineProps) {
  const vertical = orientation === 'vertical'
  return (
    <span
      aria-hidden="true"
      data-state={state}
      className={cn(
        'relative block rounded-full transition-colors duration-slow ease-soft',
        // Импульс обрезается по концам линии, но ореол может выходить в стороны.
        vertical ? 'w-px [clip-path:inset(0_-6px)]' : 'h-px [clip-path:inset(-6px_0)]',
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
              ? '-inset-x-px top-0 h-2/5 animate-flow-y bg-linear-to-b'
              : '-inset-y-px left-0 w-2/5 animate-flow bg-linear-to-r',
            'rounded-full shadow-[0_0_8px_1px_color-mix(in_oklab,var(--color-accent)_45%,transparent)]',
          )}
        />
      )}
    </span>
  )
}
