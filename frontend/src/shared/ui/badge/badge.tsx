import { cva } from 'class-variance-authority'
import type { ReactNode } from 'react'
import { cn } from '@/shared/lib/cn'
import { Icon, type IconName } from '../icon'

/** Тон — смысл, а не украшение: accent — в работе, amber — допущение и внимание, success — решено, danger — ошибка. */
export type BadgeTone = 'neutral' | 'accent' | 'amber' | 'success' | 'danger'

const badgeVariants = cva(
  'inline-flex h-5 shrink-0 items-center gap-1 whitespace-nowrap rounded-sm px-1.5 text-xs font-medium leading-none',
  {
    variants: {
      variant: { subtle: '', outline: 'border bg-transparent' },
      tone: { neutral: '', accent: '', amber: '', success: '', danger: '' },
    },
    compoundVariants: [
      { variant: 'subtle', tone: 'neutral', className: 'bg-pressed text-fg-muted' },
      { variant: 'subtle', tone: 'accent', className: 'bg-accent-subtle text-accent-fg' },
      { variant: 'subtle', tone: 'amber', className: 'bg-amber-subtle text-amber-fg' },
      { variant: 'subtle', tone: 'success', className: 'bg-success-subtle text-success-fg' },
      { variant: 'subtle', tone: 'danger', className: 'bg-danger-subtle text-danger-fg' },
      { variant: 'outline', tone: 'neutral', className: 'border-border text-fg-muted' },
      { variant: 'outline', tone: 'accent', className: 'border-accent/35 text-accent-fg' },
      { variant: 'outline', tone: 'amber', className: 'border-amber/45 text-amber-fg' },
      { variant: 'outline', tone: 'success', className: 'border-success/40 text-success-fg' },
      { variant: 'outline', tone: 'danger', className: 'border-danger/40 text-danger-fg' },
    ],
    defaultVariants: { variant: 'subtle', tone: 'neutral' },
  },
)

const dotTone: Record<BadgeTone, string> = {
  neutral: 'bg-fg-subtle',
  accent: 'bg-accent',
  amber: 'bg-amber',
  success: 'bg-success',
  danger: 'bg-danger',
}

export interface BadgeProps {
  tone?: BadgeTone
  /** subtle — по умолчанию; outline — когда рядом много заливок. */
  variant?: 'subtle' | 'outline'
  icon?: IconName
  /** Цветная точка статуса слева. */
  dot?: boolean
  className?: string
  children: ReactNode
}

/** Короткая неинтерактивная метка статуса или количества. */
export function Badge({
  tone = 'neutral',
  variant = 'subtle',
  icon,
  dot,
  className,
  children,
}: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ variant, tone }), className)}>
      {dot && <span aria-hidden="true" className={cn('size-1.5 rounded-full', dotTone[tone])} />}
      {icon && <Icon name={icon} size={14} className="-ml-0.5" />}
      {children}
    </span>
  )
}
