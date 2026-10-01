import type { ReactNode } from 'react'
import { Toaster as SonnerToaster, toast as sonnerToast } from 'sonner'
import { cn } from '@/shared/lib/cn'
import { buttonVariants } from '../button/button'
import { Icon } from '../icon'

/** Ставится один раз в корне приложения. Уведомления — снизу справа, не больше трёх сразу. */
export function Toaster() {
  return (
    <SonnerToaster
      position="bottom-right"
      gap={8}
      offset={20}
      visibleToasts={3}
      duration={5000}
      containerAriaLabel="Уведомления"
      icons={{
        success: <Icon name="circle-check" className="text-success" />,
        error: <Icon name="alert-circle" className="text-danger" />,
        warning: <Icon name="alert-triangle" className="text-amber" />,
        info: <Icon name="info" className="text-accent" />,
      }}
      toastOptions={{
        unstyled: true,
        closeButtonAriaLabel: 'Закрыть уведомление',
        classNames: {
          toast: cn(
            'group/toast pointer-events-auto flex w-[22.5rem] items-start gap-2.5 rounded-lg border border-border',
            'bg-surface-raised p-3.5 text-sm text-fg shadow-lg',
          ),
          icon: 'mt-0.5 flex size-4 shrink-0 items-center justify-center [&>svg]:size-4',
          content: 'flex min-w-0 flex-1 flex-col gap-0.5',
          title: 'font-medium leading-5 text-fg',
          description: 'leading-5 text-fg-muted',
          actionButton: cn(
            buttonVariants({ variant: 'secondary', size: 'sm' }),
            'ml-2 self-center',
          ),
          cancelButton: cn(buttonVariants({ variant: 'ghost', size: 'sm' }), 'self-center'),
        },
      }}
    />
  )
}

export interface ToastOptions {
  /** Одна фраза-уточнение. Не повторяет заголовок. */
  description?: ReactNode
  /** Одно действие: «Отменить», «Открыть». */
  action?: { label: string; onClick: () => void }
  /** Мс. Для ошибок с действием — дольше, по умолчанию 5000. */
  duration?: number
  /** Повторный вызов с тем же id обновляет уведомление, а не создаёт новое. */
  id?: string | number
}

function options(opts?: ToastOptions) {
  if (!opts) return undefined
  return {
    description: opts.description,
    duration: opts.duration,
    id: opts.id,
    action: opts.action
      ? { label: opts.action.label, onClick: () => opts.action?.onClick() }
      : undefined,
  }
}

/**
 * Короткое уведомление о результате действия. Заголовок — что произошло, в прошедшем времени:
 * «Источник добавлен», «Схема сохранена». Для ошибок — что не получилось и что сделать.
 */
export const toast = Object.assign(
  (title: string, opts?: ToastOptions) => sonnerToast(title, options(opts)),
  {
    success: (title: string, opts?: ToastOptions) => sonnerToast.success(title, options(opts)),
    error: (title: string, opts?: ToastOptions) => sonnerToast.error(title, options(opts)),
    warning: (title: string, opts?: ToastOptions) => sonnerToast.warning(title, options(opts)),
    info: (title: string, opts?: ToastOptions) => sonnerToast.info(title, options(opts)),
    dismiss: (id?: string | number) => sonnerToast.dismiss(id),
  },
)
