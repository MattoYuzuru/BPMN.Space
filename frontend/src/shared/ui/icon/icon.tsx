import { cn } from '@/shared/lib/cn'
import { type IconName, iconRegistry } from './registry'

/** Разрешённые размеры: 14 — в плотных строках, 16 — по умолчанию, 20 и 24 — пустые состояния. */
export type IconSize = 14 | 16 | 20 | 24

export interface IconProps {
  name: IconName
  size?: IconSize
  /** Подпись для иконки, которая несёт смысл сама по себе. Без неё иконка скрыта от скринридера. */
  label?: string
  className?: string
}

/** Иконка Tabler с единой обводкой 1.5. Единственный способ показать иконку в интерфейсе. */
export function Icon({ name, size = 16, label, className }: IconProps) {
  const Component = iconRegistry[name]
  return (
    <Component
      size={size}
      stroke={1.5}
      className={cn('shrink-0', className)}
      aria-hidden={label ? undefined : true}
      aria-label={label}
      role={label ? 'img' : undefined}
      focusable="false"
      data-icon={name}
    />
  )
}
