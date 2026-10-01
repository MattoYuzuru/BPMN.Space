import { cva, type VariantProps } from 'class-variance-authority'
import { Slot } from 'radix-ui'
import type { ComponentProps } from 'react'
import { cn } from '@/shared/lib/cn'
import { Icon, type IconName } from '../icon'
import { Spinner } from '../spinner/spinner'

/**
 * Три уровня важности: primary — одно главное действие на экране, secondary — обычные действия,
 * ghost — действия в тулбарах и строках. Тон danger — только для разрушительных действий.
 */
export const buttonVariants = cva(
  [
    'group/button relative inline-flex shrink-0 cursor-pointer select-none items-center justify-center whitespace-nowrap font-medium',
    'transition-[color,background-color,border-color,box-shadow,opacity,scale] duration-(--duration-base) ease-soft',
    'active:scale-[0.98] disabled:pointer-events-none disabled:opacity-45 aria-busy:pointer-events-none',
  ],
  {
    variants: {
      variant: {
        primary:
          'bg-accent text-fg-on-accent shadow-[inset_0_1px_0_oklch(1_0_0/0.16),var(--shadow-xs)] hover:bg-accent-hover',
        secondary:
          'border border-border bg-surface text-fg shadow-xs hover:border-border-strong hover:bg-surface-hover',
        ghost:
          'text-fg-muted hover:bg-hover hover:text-fg active:bg-pressed data-[state=open]:bg-pressed data-[state=open]:text-fg',
      },
      tone: { default: '', danger: '' },
      size: {
        sm: 'h-7 gap-1.5 rounded-sm px-2.5 text-xs',
        md: 'h-8 gap-1.5 rounded-md px-3 text-sm',
        lg: 'h-10 gap-2 rounded-md px-4 text-base',
      },
    },
    compoundVariants: [
      { variant: 'primary', tone: 'danger', className: 'bg-danger hover:bg-danger-hover' },
      {
        variant: 'secondary',
        tone: 'danger',
        className: 'text-danger-fg hover:border-danger/40 hover:bg-danger-subtle',
      },
      {
        variant: 'ghost',
        tone: 'danger',
        className: 'text-danger-fg hover:bg-danger-subtle hover:text-danger-fg',
      },
    ],
    defaultVariants: { variant: 'secondary', tone: 'default', size: 'md' },
  },
)

export type ButtonVariant = 'primary' | 'secondary' | 'ghost'
export type ButtonSize = 'sm' | 'md' | 'lg'

export interface ButtonProps extends ComponentProps<'button'>, VariantProps<typeof buttonVariants> {
  /** Иконка слева от подписи. */
  leadingIcon?: IconName
  /** Иконка справа (стрелка «дальше», шеврон меню). */
  trailingIcon?: IconName
  /** Идёт действие: кнопка неактивна, вместо подписи — индикатор, ширина не меняется. */
  loading?: boolean
  /** Отрисовать дочерний элемент (ссылку) со стилями кнопки. */
  asChild?: boolean
}

export function Button({
  variant,
  tone,
  size,
  leadingIcon,
  trailingIcon,
  loading = false,
  asChild = false,
  disabled,
  className,
  children,
  type = 'button',
  ...props
}: ButtonProps) {
  const classes = cn(buttonVariants({ variant, tone, size }), className)
  if (asChild) {
    return (
      <Slot.Root className={classes} {...props}>
        {children}
      </Slot.Root>
    )
  }
  const iconSize = size === 'sm' ? 14 : 16
  return (
    <button
      type={type}
      className={classes}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      <span
        className={cn(
          'inline-flex items-center gap-[inherit] transition-opacity duration-(--duration-fast)',
          loading && 'opacity-0',
        )}
      >
        {leadingIcon && <Icon name={leadingIcon} size={iconSize} className="-ml-0.5" />}
        {children}
        {trailingIcon && <Icon name={trailingIcon} size={iconSize} className="-mr-0.5" />}
      </span>
      {loading && (
        <span className="absolute inset-0 grid place-items-center animate-fade-in">
          <Spinner size={iconSize} />
        </span>
      )}
    </button>
  )
}
