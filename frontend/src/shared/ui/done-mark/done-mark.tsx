import { cn } from '@/shared/lib/cn'
import { Icon } from '../icon'

export interface DoneMarkProps {
  /** Отмечено ли действие. Пользователь отметку руками не ставит — её ставит система. */
  done: boolean
  className?: string
}

/**
 * Круглая отметка выполненного действия в списках («Начало работы»). Это не флажок: она не
 * интерактивна и ничего не принимает от пользователя. Пустая — кольцо, выполненная — Хвоя с
 * галочкой; смена состояния плавная (320 мс), при `prefers-reduced-motion` — сразу.
 */
export function DoneMark({ done, className }: DoneMarkProps) {
  return (
    <span
      aria-hidden="true"
      data-done={done || undefined}
      className={cn(
        'inline-grid size-5 shrink-0 place-items-center rounded-full border text-fg-on-accent',
        'transition-[background-color,border-color] duration-slow ease-soft motion-reduce:transition-none',
        done ? 'border-success bg-success' : 'border-control bg-surface',
        className,
      )}
    >
      <Icon
        name="check"
        size={14}
        className={cn(
          'transition-[opacity,scale] duration-slow ease-soft motion-reduce:transition-none',
          done ? 'scale-100 opacity-100' : 'scale-50 opacity-0',
        )}
      />
    </span>
  )
}
