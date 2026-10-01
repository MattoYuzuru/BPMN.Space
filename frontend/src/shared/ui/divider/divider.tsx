import { Separator } from 'radix-ui'
import type { ReactNode } from 'react'
import { cn } from '@/shared/lib/cn'

export interface DividerProps {
  orientation?: 'horizontal' | 'vertical'
  /** Короткая подпись посередине линии: «или», «Вчера». */
  label?: ReactNode
  className?: string
}

/** Тонкая линия между группами. Чаще хватает отступа — линию ставим, когда группы сливаются. */
export function Divider({ orientation = 'horizontal', label, className }: DividerProps) {
  if (label && orientation === 'horizontal') {
    return (
      <div className={cn('flex items-center gap-3', className)}>
        <Separator.Root decorative className="h-px flex-1 bg-border" />
        <span className="type-caption text-fg-subtle">{label}</span>
        <Separator.Root decorative className="h-px flex-1 bg-border" />
      </div>
    )
  }
  return (
    <Separator.Root
      decorative
      orientation={orientation}
      className={cn(
        'shrink-0 bg-border',
        orientation === 'horizontal' ? 'h-px w-full' : 'h-full w-px self-stretch',
        className,
      )}
    />
  )
}
