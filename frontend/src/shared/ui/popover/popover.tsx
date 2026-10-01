import { Popover as PopoverPrimitive } from 'radix-ui'
import type { ComponentProps } from 'react'
import { cn } from '@/shared/lib/cn'
import { floatingSurface } from '../styles'

export const Popover = PopoverPrimitive.Root
export const PopoverTrigger = PopoverPrimitive.Trigger
export const PopoverAnchor = PopoverPrimitive.Anchor
export const PopoverClose = PopoverPrimitive.Close

/** Всплывающая панель у элемента: фильтры, быстрые настройки, детали цитаты. */
export function PopoverContent({
  className,
  sideOffset = 8,
  align = 'center',
  ...props
}: ComponentProps<typeof PopoverPrimitive.Content>) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Content
        sideOffset={sideOffset}
        align={align}
        collisionPadding={12}
        className={cn(floatingSurface, 'w-72 rounded-lg p-4', className)}
        {...props}
      />
    </PopoverPrimitive.Portal>
  )
}
