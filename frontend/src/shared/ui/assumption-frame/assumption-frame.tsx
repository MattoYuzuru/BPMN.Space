import type { ReactNode } from 'react'
import { cn } from '@/shared/lib/cn'
import { Icon } from '../icon'

export interface AssumptionFrameProps {
  /** Подпись над текстом. По умолчанию «Допущение»; null — без подписи. */
  label?: ReactNode
  /** Действия справа от подписи: «Принять», «Ответить». */
  actions?: ReactNode
  className?: string
  children: ReactNode
}

/**
 * Фирменный приём «Янтарный пунктир»: всё, что система предположила сама, обведено
 * янтарным пунктиром. При наведении пунктир медленно течёт — допущение «живое», его можно уточнить.
 */
export function AssumptionFrame({
  label = 'Допущение',
  actions,
  className,
  children,
}: AssumptionFrameProps) {
  return (
    <div
      className={cn(
        'group/assumption relative rounded-md bg-amber-subtle/70 px-3 py-2.5',
        'transition-colors duration-(--duration-base) ease-soft hover:bg-amber-subtle',
        className,
      )}
    >
      <svg
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 size-full overflow-visible text-amber"
      >
        <rect
          width="100%"
          height="100%"
          rx="8"
          fill="none"
          stroke="currentColor"
          strokeWidth="1"
          strokeDasharray="4 3"
          className="group-hover/assumption:animate-dash group-focus-within/assumption:animate-dash motion-reduce:animate-none"
        />
      </svg>
      {(label || actions) && (
        <div className="mb-1 flex min-h-6 items-center justify-between gap-2">
          {label && (
            <span className="flex items-center gap-1.5 type-label text-amber-fg">
              <Icon name="assumption" size={14} />
              {label}
            </span>
          )}
          {actions && <div className="-mr-1 flex items-center gap-1">{actions}</div>}
        </div>
      )}
      <div className="type-ui text-fg">{children}</div>
    </div>
  )
}
