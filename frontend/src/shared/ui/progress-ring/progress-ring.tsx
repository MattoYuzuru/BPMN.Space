import { cn } from '@/shared/lib/cn'
import { Icon } from '../icon'

export interface ProgressRingProps {
  /** Сколько выполнено. */
  value: number
  /** Сколько всего. */
  max: number
  /** Диаметр в пикселях. */
  size?: number
  /** Подпись для скринридера, например «Выполнено 5 из 12». Без неё кольцо скрыто. */
  label?: string
  className?: string
}

const STROKE = 2

/**
 * Малое кольцо прогресса: дуга Тока по дорожке, а при `value >= max` — Хвоя с галочкой внутри.
 * Дуга растёт мягко (320 мс), при `prefers-reduced-motion` — сразу.
 */
export function ProgressRing({ value, max, size = 20, label, className }: ProgressRingProps) {
  const complete = max > 0 && value >= max
  const ratio = max > 0 ? Math.min(1, Math.max(0, value / max)) : 0
  const radius = (size - STROKE) / 2
  const circumference = 2 * Math.PI * radius
  const a11y = label ? { role: 'img', 'aria-label': label } : { 'aria-hidden': true as const }
  return (
    <span
      {...a11y}
      data-complete={complete || undefined}
      style={{ width: size, height: size }}
      className={cn('relative inline-grid shrink-0 place-items-center', className)}
    >
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        className="absolute inset-0 -rotate-90"
        aria-hidden="true"
        focusable="false"
      >
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={STROKE}
          className={complete ? 'stroke-success' : 'stroke-pressed'}
        />
        {!complete && ratio > 0 && (
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            strokeWidth={STROKE}
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={circumference * (1 - ratio)}
            className="stroke-accent transition-[stroke-dashoffset] duration-slow ease-soft motion-reduce:transition-none"
          />
        )}
      </svg>
      {complete && <Icon name="check" size={14} className="relative text-success-fg" />}
    </span>
  )
}
