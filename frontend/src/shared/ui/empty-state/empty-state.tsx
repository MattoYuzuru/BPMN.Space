import type { ReactNode } from 'react'
import { cn } from '@/shared/lib/cn'
import { GridBackdrop } from '../grid-backdrop/grid-backdrop'
import { Icon, type IconName } from '../icon'

export interface EmptyStateProps {
  icon: IconName
  /** Что здесь будет: «Источников пока нет». Без восклицаний. */
  title: ReactNode
  /** Одна фраза, если без неё непонятно, что делать. Часто не нужна. */
  description?: ReactNode
  /** Главное действие (Button primary) и, если нужно, второстепенное. */
  action?: ReactNode
  /** Подложка: сетка — для главной области экрана, none — для мелких панелей. */
  backdrop?: 'grid' | 'dots' | 'none'
  size?: 'sm' | 'md'
  className?: string
}

/** Пустое состояние области: иконка, заголовок, действие. На фоне — фирменная сетка. */
export function EmptyState({
  icon,
  title,
  description,
  action,
  backdrop = 'grid',
  size = 'md',
  className,
}: EmptyStateProps) {
  const large = size === 'md'
  return (
    <div
      className={cn(
        'relative isolate flex flex-col items-center justify-center text-center',
        large ? 'gap-4 px-6 py-16' : 'gap-3 px-4 py-8',
        className,
      )}
    >
      {backdrop !== 'none' && <GridBackdrop pattern={backdrop} glow={large} />}
      <div
        className={cn(
          'relative grid place-items-center rounded-lg border border-border bg-surface text-fg-muted shadow-sm',
          large ? 'size-11' : 'size-9',
        )}
      >
        <Icon name={icon} size={large ? 20 : 16} />
      </div>
      <div className="flex max-w-sm flex-col gap-1">
        <div className={cn('text-fg', large ? 'type-heading' : 'type-subheading')}>{title}</div>
        {description && <p className="type-ui text-fg-muted">{description}</p>}
      </div>
      {action && <div className="mt-1 flex items-center gap-2">{action}</div>}
    </div>
  )
}
