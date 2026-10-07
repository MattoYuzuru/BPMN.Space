import { cn } from '@/shared/lib/cn'

export interface AudioLevelProps {
  /** Уровни сигнала 0..1, последние справа. Берутся последние `bars` значений. */
  levels: readonly number[]
  bars?: number
  /** Идёт запись: полосы цвета тока. Иначе — приглушённые. */
  active?: boolean
  /** Подпись для скринридера: «Уровень сигнала микрофона». */
  label: string
  className?: string
}

/**
 * Уровень сигнала микрофона: ряд вертикальных полос, симметричных относительно середины.
 * Полосы масштабируются трансформацией — без перерисовки раскладки, плавно и дёшево.
 */
export function AudioLevel({
  levels,
  bars = 40,
  active = true,
  label,
  className,
}: AudioLevelProps) {
  const tail = levels.slice(-bars)
  const padded = [...Array.from({ length: Math.max(0, bars - tail.length) }, () => 0), ...tail]
  const peak = tail.length ? Math.max(...tail) : 0
  return (
    // biome-ignore lint/a11y/useSemanticElements: <meter> не стилизуется полосами; роль и значения те же
    <div
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(peak * 100)}
      className={cn(
        'flex h-14 items-center justify-center gap-1 transition-colors duration-slow ease-soft',
        active ? 'text-accent' : 'text-fg-subtle',
        className,
      )}
    >
      {padded.map((level, index) => (
        <span
          // biome-ignore lint/suspicious/noArrayIndexKey: полосы — позиции, а не сущности
          key={index}
          aria-hidden="true"
          className="h-full w-1 min-w-0 shrink rounded-full bg-current transition-transform duration-fast ease-soft motion-reduce:transition-none"
          style={{ transform: `scaleY(${Math.max(0.06, Math.min(1, level))})` }}
        />
      ))}
    </div>
  )
}
