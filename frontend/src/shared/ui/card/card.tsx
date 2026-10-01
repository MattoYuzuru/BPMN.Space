import { cva } from 'class-variance-authority'
import { Slot } from 'radix-ui'
import type { ComponentProps, ReactNode } from 'react'
import { cn } from '@/shared/lib/cn'
import { Icon, type IconName } from '../icon'

const cardVariants = cva('relative rounded-lg text-fg', {
  variants: {
    variant: {
      outline: 'border border-border bg-surface',
      elevated: 'border border-border bg-surface shadow-sm',
      sunken: 'border border-transparent bg-bg-subtle',
    },
    padding: { none: '', sm: 'p-3', md: 'p-4', lg: 'p-6' },
    interactive: {
      true: [
        'cursor-pointer outline-none transition-[border-color,box-shadow,background-color] duration-(--duration-base) ease-soft',
        'hover:border-border-strong hover:shadow-sm focus-visible:border-accent focus-visible:ring-3 focus-visible:ring-accent/15',
        'data-[state=active]:border-accent/50 aria-[current=true]:border-accent/50',
      ],
      false: '',
    },
    glow: { true: 'border-accent/45 shadow-glow', false: '' },
  },
  defaultVariants: { variant: 'outline', padding: 'md', interactive: false, glow: false },
})

export interface CardProps extends ComponentProps<'div'> {
  /** outline — по умолчанию; elevated — карточка над фоном; sunken — вложенный блок (цитата, пример). */
  variant?: 'outline' | 'elevated' | 'sunken'
  padding?: 'none' | 'sm' | 'md' | 'lg'
  /** Реагирует на наведение и фокус. Вместе с asChild — карточка-ссылка или кнопка. */
  interactive?: boolean
  /** Свечение тока: выделяет одну активную карточку (текущий прогон, выбранный вопрос). */
  glow?: boolean
  asChild?: boolean
}

/** Контейнер для группы связанного содержимого. Карточки не вкладываем друг в друга. */
export function Card({
  variant,
  padding,
  interactive,
  glow,
  asChild,
  className,
  ...props
}: CardProps) {
  const Component = asChild ? Slot.Root : 'div'
  return (
    <Component
      className={cn(cardVariants({ variant, padding, interactive, glow }), className)}
      {...props}
    />
  )
}

export interface CardHeaderProps {
  title: ReactNode
  description?: ReactNode
  icon?: IconName
  /** Действия справа: IconButton, DropdownMenu. */
  actions?: ReactNode
  className?: string
}

export function CardHeader({ title, description, icon, actions, className }: CardHeaderProps) {
  return (
    <div className={cn('flex items-start gap-3', className)}>
      {icon && (
        <span className="mt-px grid size-7 shrink-0 place-items-center rounded-md border border-border bg-bg-subtle text-fg-muted">
          <Icon name={icon} size={16} />
        </span>
      )}
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <div className="type-subheading truncate text-fg">{title}</div>
        {description && <div className="type-caption text-fg-muted">{description}</div>}
      </div>
      {actions && <div className="-mt-1 -mr-1 flex shrink-0 items-center gap-1">{actions}</div>}
    </div>
  )
}
