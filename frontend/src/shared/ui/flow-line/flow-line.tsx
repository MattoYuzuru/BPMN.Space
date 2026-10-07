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
        vertical ? 'w-px' : 'h-px',
        state === 'done' ? 'bg-accent/45' : 'bg-border-strong',
        state === 'active' && 'motion-reduce:bg-accent/45',
        className,
      )}
    >
      {state === 'active' && (
        <span
          className={cn(
            // Маска гасит ореол до границ дорожки: конец импульса не превращается в срез.
            'absolute overflow-hidden motion-reduce:hidden',
            vertical
              ? '-inset-x-1.5 inset-y-0 [mask-image:linear-gradient(to_bottom,transparent,black_8px,black_calc(100%_-_8px),transparent)]'
              : '-inset-y-1.5 inset-x-0 [mask-image:linear-gradient(to_right,transparent,black_8px,black_calc(100%_-_8px),transparent)]',
          )}
        >
          <span
            className={cn(
              'absolute rounded-full from-transparent via-accent to-transparent shadow-[0_0_8px_1px_color-mix(in_oklab,var(--color-accent)_45%,transparent)]',
              vertical
                ? 'top-0 left-1/2 h-2/5 w-0.5 -translate-x-1/2 animate-flow-y bg-linear-to-b'
                : 'top-1/2 left-0 h-0.5 w-2/5 -translate-y-1/2 animate-flow bg-linear-to-r',
            )}
          />
        </span>
      )}
    </span>
  )
}
