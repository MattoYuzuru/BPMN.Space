import type { ComponentProps } from 'react'
import { Group, Panel, Separator } from 'react-resizable-panels'
import { cn } from '@/shared/lib/cn'

/**
 * Панели с изменяемым размером: источники | схема | вопросы.
 * Размеры: число — пиксели, строка без единиц — проценты ("25"), можно "20rem".
 * Сохранить раскладку между сессиями — хук useDefaultLayout из react-resizable-panels.
 */
export function ResizablePanelGroup({ className, ...props }: ComponentProps<typeof Group>) {
  return <Group className={cn('size-full', className)} {...props} />
}

export const ResizablePanel = Panel

/** Разделитель: тонкая линия, при наведении и перетаскивании проявляется акцентом. */
export function ResizableHandle({ className, ...props }: ComponentProps<typeof Separator>) {
  return (
    <Separator
      className={cn(
        'group/handle relative flex shrink-0 items-center justify-center bg-border outline-none',
        'transition-colors delay-75 duration-(--duration-base) ease-soft',
        'aria-[orientation=vertical]:w-px aria-[orientation=horizontal]:h-px',
        'data-[separator=hover]:bg-accent/50 data-[separator=active]:bg-accent data-[separator=focus]:bg-accent',
        className,
      )}
      {...props}
    >
      <span
        aria-hidden="true"
        className={cn(
          'pointer-events-none absolute rounded-full bg-accent/0 transition-colors delay-75 duration-(--duration-base) ease-soft',
          'group-aria-[orientation=vertical]/handle:inset-y-0 group-aria-[orientation=vertical]/handle:-inset-x-px',
          'group-aria-[orientation=horizontal]/handle:inset-x-0 group-aria-[orientation=horizontal]/handle:-inset-y-px',
          'group-data-[separator=active]/handle:bg-accent/30 group-data-[separator=hover]/handle:bg-accent/15',
        )}
      />
    </Separator>
  )
}
