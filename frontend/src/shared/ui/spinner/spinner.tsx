import { cn } from '@/shared/lib/cn'

/**
 * Индикатор загрузки внутри кнопки. Наружу из дизайн-системы не экспортируется:
 * загрузку областей показываем скелетонами (Skeleton), а ход процесса — Stepper и Progress.
 */
export function Spinner({ size = 16, className }: { size?: 14 | 16; className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      width={size}
      height={size}
      fill="none"
      aria-hidden="true"
      className={cn('shrink-0 animate-spin motion-reduce:animate-none', className)}
    >
      <circle cx="8" cy="8" r="6.25" stroke="currentColor" strokeOpacity="0.25" strokeWidth="1.5" />
      <path
        d="M14.25 8A6.25 6.25 0 0 0 8 1.75"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  )
}
