import { AlertDialog } from 'radix-ui'
import { type MouseEvent, type ReactElement, type ReactNode, useState } from 'react'
import { cn } from '@/shared/lib/cn'
import { Button } from '../button/button'
import { overlayClass } from './dialog'

export interface ConfirmDialogProps {
  /** Вопрос: «Удалить источник?» */
  title: ReactNode
  /** Что произойдёт: «Вопросы, которые на него ссылаются, вернутся в открытые». */
  description?: ReactNode
  /** Глагол действия: «Удалить», «Перестроить». Не «Да» и не «ОК». */
  confirmLabel: string
  cancelLabel?: string
  tone?: 'default' | 'danger'
  /** Может вернуть Promise — кнопка покажет загрузку, окно закроется после успеха. */
  onConfirm: () => void | Promise<void>
  open?: boolean
  onOpenChange?: (open: boolean) => void
  /** Элемент, открывающий окно (если состояние не контролируется снаружи). */
  trigger?: ReactElement
}

/**
 * Подтверждение необратимого действия. Вместо window.confirm.
 * Если onConfirm бросает ошибку, окно остаётся открытым — сообщите об ошибке через toast.error.
 */
export function ConfirmDialog({
  title,
  description,
  confirmLabel,
  cancelLabel = 'Отмена',
  tone = 'default',
  onConfirm,
  open: openProp,
  onOpenChange,
  trigger,
}: ConfirmDialogProps) {
  const [openState, setOpenState] = useState(false)
  const [pending, setPending] = useState(false)
  const open = openProp ?? openState
  const setOpen = (next: boolean) => {
    if (pending) return
    if (openProp === undefined) setOpenState(next)
    onOpenChange?.(next)
  }

  const confirm = async (event: MouseEvent) => {
    event.preventDefault()
    setPending(true)
    try {
      await onConfirm()
      setPending(false)
      if (openProp === undefined) setOpenState(false)
      onOpenChange?.(false)
    } catch {
      setPending(false)
    }
  }

  return (
    <AlertDialog.Root open={open} onOpenChange={setOpen}>
      {trigger && <AlertDialog.Trigger asChild>{trigger}</AlertDialog.Trigger>}
      <AlertDialog.Portal>
        <AlertDialog.Overlay className={overlayClass} />
        <AlertDialog.Content
          {...(description ? {} : { 'aria-describedby': undefined })}
          className={cn(
            'motion-dialog fixed inset-0 z-50 m-auto flex h-fit w-[calc(100vw-2rem)] max-w-[25rem] flex-col gap-5',
            'rounded-lg border border-border bg-surface p-5 text-fg shadow-lg outline-none',
          )}
        >
          <div className="flex flex-col gap-1.5">
            <AlertDialog.Title className="type-heading text-fg">{title}</AlertDialog.Title>
            {description && (
              <AlertDialog.Description className="type-ui text-fg-muted">
                {description}
              </AlertDialog.Description>
            )}
          </div>
          <div className="flex items-center justify-end gap-2">
            <AlertDialog.Cancel asChild>
              <Button variant="ghost" disabled={pending}>
                {cancelLabel}
              </Button>
            </AlertDialog.Cancel>
            <Button variant="primary" tone={tone} loading={pending} onClick={confirm}>
              {confirmLabel}
            </Button>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  )
}
