import { Dialog as DialogPrimitive } from 'radix-ui'
import type { ComponentProps, ReactNode } from 'react'
import { cn } from '@/shared/lib/cn'
import { guardTourLayer } from '@/shared/lib/tour-anchors'
import { overlayClass } from '../dialog/dialog'
import { IconButton } from '../icon-button/icon-button'

export const Sheet = DialogPrimitive.Root
export const SheetTrigger = DialogPrimitive.Trigger
export const SheetClose = DialogPrimitive.Close

const widths = {
  sm: 'w-[min(23.75rem,calc(100vw-1rem))]',
  md: 'w-[min(30rem,calc(100vw-1rem))]',
  lg: 'w-[min(40rem,calc(100vw-1rem))]',
} as const

export interface SheetContentProps
  extends Omit<ComponentProps<typeof DialogPrimitive.Content>, 'title'> {
  title: ReactNode
  description?: ReactNode
  footer?: ReactNode
  size?: keyof typeof widths
}

/**
 * Боковая панель справа: детали вопроса, история версий, настройки проекта.
 * Плавает с отступом от краёв окна, выезжает мягко.
 */
export function SheetContent({
  title,
  description,
  footer,
  size = 'md',
  className,
  children,
  onInteractOutside,
  onEscapeKeyDown,
  ...props
}: SheetContentProps) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className={overlayClass} />
      <DialogPrimitive.Content
        {...(description ? {} : { 'aria-describedby': undefined })}
        className={cn(
          'motion-sheet fixed inset-y-2 right-2 z-50 flex flex-col',
          'rounded-lg border border-border bg-surface text-fg shadow-lg outline-none',
          widths[size],
          className,
        )}
        {...props}
        // Клик и Esc внутри слоя обучения не закрывают панель.
        onInteractOutside={(event) => {
          guardTourLayer(event)
          onInteractOutside?.(event)
        }}
        onEscapeKeyDown={(event) => {
          guardTourLayer(event)
          onEscapeKeyDown?.(event)
        }}
      >
        <div className="flex flex-col gap-1 border-b border-border px-5 pt-4 pb-3.5 pr-12">
          <DialogPrimitive.Title className="type-heading text-fg">{title}</DialogPrimitive.Title>
          {description && (
            <DialogPrimitive.Description className="type-ui text-fg-muted">
              {description}
            </DialogPrimitive.Description>
          )}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && (
          <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-3.5">
            {footer}
          </div>
        )}
        <DialogPrimitive.Close asChild>
          <IconButton
            icon="x"
            label="Закрыть"
            size="sm"
            tooltip={false}
            className="absolute top-3 right-3"
          />
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  )
}
