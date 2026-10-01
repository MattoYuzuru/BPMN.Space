import { Tooltip as TooltipPrimitive } from 'radix-ui'
import type { ReactElement, ReactNode } from 'react'
import { cn } from '@/shared/lib/cn'
import { Kbd, type KeyName } from '../kbd/kbd'
import { floatingSurface } from '../styles'

/** Ставится один раз в корне приложения: общая задержка и мгновенный показ соседних подсказок. */
export function TooltipProvider({ children }: { children: ReactNode }) {
  return (
    <TooltipPrimitive.Provider delayDuration={450} skipDelayDuration={250}>
      {children}
    </TooltipPrimitive.Provider>
  )
}

export interface TooltipProps {
  /** Короткая подпись: название действия, а не инструкция. */
  content: ReactNode
  /** Горячая клавиша действия. */
  shortcut?: KeyName[]
  side?: 'top' | 'right' | 'bottom' | 'left'
  align?: 'start' | 'center' | 'end'
  /** Один элемент, принимающий ref и обработчики (кнопка, ссылка). */
  children: ReactElement
  open?: boolean
  onOpenChange?: (open: boolean) => void
}

/** Подсказка при наведении и фокусе. Вместо атрибута title — его браузерный вид запрещён. */
export function Tooltip({
  content,
  shortcut,
  side = 'top',
  align = 'center',
  children,
  open,
  onOpenChange,
}: TooltipProps) {
  if (!content) return children
  return (
    <TooltipPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          side={side}
          align={align}
          sideOffset={6}
          collisionPadding={8}
          className={cn(
            floatingSurface,
            'flex max-w-xs items-center gap-2 rounded-sm px-2 py-1 text-xs leading-4 shadow-sm',
          )}
        >
          <span>{content}</span>
          {shortcut && <Kbd keys={shortcut} className="-mr-0.5" />}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  )
}
