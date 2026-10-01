import { Progress as ProgressPrimitive } from 'radix-ui'
import { cn } from '@/shared/lib/cn'

const tones = {
  accent: 'bg-accent',
  success: 'bg-success',
  amber: 'bg-amber',
} as const

export interface ProgressProps {
  /** 0..max. Без значения — неопределённый ход: по дорожке бежит импульс тока. */
  value?: number
  max?: number
  tone?: keyof typeof tones
  size?: 'sm' | 'md'
  /** Подпись для скринридера: «Загрузка документа». */
  label: string
  className?: string
}

/** Полоса хода операции: загрузка файла, распознавание голоса. */
export function Progress({
  value,
  max = 100,
  tone = 'accent',
  size = 'sm',
  label,
  className,
}: ProgressProps) {
  const indeterminate = value === undefined
  const percent = indeterminate ? 0 : Math.min(100, Math.max(0, (value / max) * 100))
  return (
    <ProgressPrimitive.Root
      value={indeterminate ? null : value}
      max={max}
      aria-label={label}
      className={cn(
        'relative w-full overflow-hidden rounded-full bg-pressed',
        size === 'sm' ? 'h-1' : 'h-1.5',
        className,
      )}
    >
      {indeterminate ? (
        <span
          className={cn(
            'absolute inset-y-0 left-0 w-2/5 animate-flow rounded-full bg-linear-to-r from-transparent to-transparent',
            tone === 'accent' && 'via-accent',
            tone === 'success' && 'via-success',
            tone === 'amber' && 'via-amber',
            'motion-reduce:w-full motion-reduce:animate-none motion-reduce:opacity-40',
          )}
        />
      ) : (
        <ProgressPrimitive.Indicator
          className={cn(
            'size-full origin-left rounded-full transition-transform duration-(--duration-slow) ease-soft',
            tones[tone],
          )}
          style={{ transform: `translateX(-${100 - percent}%)` }}
        />
      )}
    </ProgressPrimitive.Root>
  )
}
