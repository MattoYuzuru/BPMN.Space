import { cva } from 'class-variance-authority'
import type { ReactNode } from 'react'
import { cn } from '@/shared/lib/cn'
import { Icon, type IconName } from '../icon'

const tagVariants = cva(
  'inline-flex h-6 max-w-full shrink-0 items-center gap-1.5 rounded-sm border px-2 text-xs transition-colors duration-base ease-soft',
  {
    variants: {
      variant: {
        neutral: 'border-border bg-surface text-fg',
        accent: 'border-accent/30 bg-accent-subtle text-accent-fg',
        assumption: 'border-dashed border-amber bg-amber-subtle text-amber-fg',
      },
    },
    defaultVariants: { variant: 'neutral' },
  },
)

export interface TagProps {
  /** neutral — сущность (источник, роль); accent — выбранный фильтр; assumption — допущение. */
  variant?: 'neutral' | 'accent' | 'assumption'
  icon?: IconName
  /** Показать крестик удаления. */
  onRemove?: () => void
  /** Подпись крестика для скринридера, например «Убрать источник Регламент.docx». */
  removeLabel?: string
  className?: string
  children: ReactNode
}

/** Метка сущности: источник, дорожка, роль, фильтр. Может удаляться. */
export function Tag({
  variant = 'neutral',
  icon,
  onRemove,
  removeLabel = 'Убрать',
  className,
  children,
}: TagProps) {
  return (
    <span className={cn(tagVariants({ variant }), onRemove && 'pr-0.5', className)}>
      {icon && <Icon name={icon} size={14} className="-ml-0.5 opacity-80" />}
      <span className="truncate">{children}</span>
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          aria-label={removeLabel}
          className="grid size-5 cursor-pointer place-items-center rounded-xs opacity-60 transition-[opacity,background-color] duration-fast hover:bg-pressed hover:opacity-100"
        >
          <Icon name="x" size={14} />
        </button>
      )}
    </span>
  )
}
