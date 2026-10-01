import { cva } from 'class-variance-authority'
import type { ComponentProps } from 'react'
import { cn } from '@/shared/lib/cn'
import { type ButtonVariant, buttonVariants } from '../button/button'
import { Icon, type IconName } from '../icon'
import type { KeyName } from '../kbd/kbd'
import { Spinner } from '../spinner/spinner'
import { Tooltip } from '../tooltip/tooltip'

const squareSize = cva('px-0', {
  variants: {
    size: { sm: 'size-7 rounded-sm', md: 'size-8 rounded-md', lg: 'size-10 rounded-md' },
  },
  defaultVariants: { size: 'md' },
})

export interface IconButtonProps extends Omit<ComponentProps<'button'>, 'children'> {
  icon: IconName
  /** Название действия: становится aria-label и текстом подсказки. Обязательно. */
  label: string
  variant?: ButtonVariant
  tone?: 'default' | 'danger'
  size?: 'sm' | 'md' | 'lg'
  loading?: boolean
  /** Горячая клавиша — показывается в подсказке. */
  shortcut?: KeyName[]
  /** Сторона подсказки; false — без подсказки (например, если рядом уже есть подпись). */
  tooltip?: 'top' | 'right' | 'bottom' | 'left' | false
}

/** Квадратная кнопка с иконкой. Подпись всегда есть — в подсказке и для скринридера. */
export function IconButton({
  icon,
  label,
  variant = 'ghost',
  tone,
  size = 'md',
  loading = false,
  shortcut,
  tooltip = 'top',
  disabled,
  className,
  type = 'button',
  ...props
}: IconButtonProps) {
  const iconSize = size === 'lg' ? 20 : size === 'sm' ? 14 : 16
  const button = (
    <button
      type={type}
      aria-label={label}
      aria-busy={loading || undefined}
      disabled={disabled || loading}
      className={cn(buttonVariants({ variant, tone }), squareSize({ size }), className)}
      {...props}
    >
      {loading ? (
        <Spinner size={iconSize === 20 ? 16 : iconSize} />
      ) : (
        <Icon name={icon} size={iconSize} />
      )}
    </button>
  )
  if (tooltip === false) return button
  return (
    <Tooltip content={label} shortcut={shortcut} side={tooltip}>
      {button}
    </Tooltip>
  )
}
