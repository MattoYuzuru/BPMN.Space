import { Dialog as DialogPrimitive } from 'radix-ui'
import type { ComponentProps, ReactNode } from 'react'
import { cn } from '@/shared/lib/cn'
import { guardTourLayer } from '@/shared/lib/tour-anchors'
import { IconButton } from '../icon-button/icon-button'

export const Dialog = DialogPrimitive.Root
export const DialogTrigger = DialogPrimitive.Trigger
export const DialogClose = DialogPrimitive.Close

const sizes = {
  sm: 'max-w-[25rem]',
  md: 'max-w-[32.5rem]',
  lg: 'max-w-[45rem]',
} as const

export const overlayClass = 'motion-overlay fixed inset-0 z-50 bg-overlay'

export interface DialogContentProps
  extends Omit<ComponentProps<typeof DialogPrimitive.Content>, 'title'> {
  /** Заголовок — вопрос или действие: «Удалить проект?», «Новый проект». */
  title: ReactNode
  /** Одна фраза о последствиях. Не дублирует заголовок. */
  description?: ReactNode
  /** Кнопки: справа главное действие, слева от него — отмена. */
  footer?: ReactNode
  size?: keyof typeof sizes
  /** Скрыть крестик (если диалог закрывается только кнопками). */
  hideClose?: boolean
}

/** Модальное окно: затемнение, фокус заперт внутри, Esc и крестик закрывают. */
export function DialogContent({
  title,
  description,
  footer,
  size = 'md',
  hideClose = false,
  className,
  children,
  onInteractOutside,
  onEscapeKeyDown,
  ...props
}: DialogContentProps) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className={overlayClass} />
      <DialogPrimitive.Content
        // Без описания явно снимаем aria-describedby, иначе Radix ссылается на пустой id.
        {...(description ? {} : { 'aria-describedby': undefined })}
        className={cn(
          'motion-dialog fixed inset-0 z-50 m-auto flex h-fit max-h-[calc(100dvh-4rem)] w-[calc(100vw-2rem)] flex-col',
          'rounded-lg border border-border bg-surface text-fg shadow-lg outline-none',
          sizes[size],
          className,
        )}
        {...props}
        // Клик и Esc внутри слоя обучения (карточка тура) не закрывают окно.
        onInteractOutside={(event) => {
          guardTourLayer(event)
          onInteractOutside?.(event)
        }}
        onEscapeKeyDown={(event) => {
          guardTourLayer(event)
          onEscapeKeyDown?.(event)
        }}
      >
        <div className="flex flex-col gap-1.5 px-5 pt-5 pb-4 pr-12">
          <DialogPrimitive.Title className="type-heading text-fg">{title}</DialogPrimitive.Title>
          {description && (
            <DialogPrimitive.Description className="type-ui text-fg-muted">
              {description}
            </DialogPrimitive.Description>
          )}
        </div>
        {children && <div className="min-h-0 flex-auto overflow-y-auto px-5 pb-5">{children}</div>}
        {footer && (
          <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-3.5">
            {footer}
          </div>
        )}
        {!hideClose && (
          <DialogPrimitive.Close asChild>
            <IconButton
              icon="x"
              label="Закрыть"
              size="sm"
              tooltip={false}
              className="absolute top-3.5 right-3.5"
            />
          </DialogPrimitive.Close>
        )}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  )
}
