import { ScrollArea as ScrollAreaPrimitive } from 'radix-ui'
import type { ComponentProps, ReactNode, Ref } from 'react'
import { cn } from '@/shared/lib/cn'

export interface ScrollAreaProps
  extends Omit<ComponentProps<typeof ScrollAreaPrimitive.Root>, 'type'> {
  /** Направление прокрутки. */
  orientation?: 'vertical' | 'horizontal' | 'both'
  /** ref на прокручиваемый элемент — для виртуализации (@tanstack/react-virtual) и автоскролла. */
  viewportRef?: Ref<HTMLDivElement>
  viewportClassName?: string
  children: ReactNode
}

/**
 * Прокручиваемая область с тонким скроллбаром, который проявляется при наведении.
 * Единственный способ сделать прокрутку в экранах (design-lint запрещает overflow-auto/scroll).
 * Высота задаётся родителем: className="h-full" или фиксированная.
 */
export function ScrollArea({
  orientation = 'vertical',
  viewportRef,
  viewportClassName,
  className,
  children,
  ...props
}: ScrollAreaProps) {
  return (
    <ScrollAreaPrimitive.Root
      type="hover"
      scrollHideDelay={700}
      className={cn('relative overflow-hidden', className)}
      {...props}
    >
      <ScrollAreaPrimitive.Viewport
        ref={viewportRef}
        className={cn(
          'size-full rounded-[inherit] outline-none focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:ring-inset',
          // Radix оборачивает содержимое в display:table — ломает truncate. Возвращаем блок.
          orientation === 'vertical' && '[&>div]:block!',
          viewportClassName,
        )}
      >
        {children}
      </ScrollAreaPrimitive.Viewport>
      {orientation !== 'horizontal' && <ScrollBar orientation="vertical" />}
      {orientation !== 'vertical' && <ScrollBar orientation="horizontal" />}
      <ScrollAreaPrimitive.Corner />
    </ScrollAreaPrimitive.Root>
  )
}

function ScrollBar({ orientation }: { orientation: 'vertical' | 'horizontal' }) {
  return (
    <ScrollAreaPrimitive.Scrollbar
      orientation={orientation}
      forceMount
      className={cn(
        'z-10 flex touch-none select-none p-0.5',
        'transition-opacity duration-(--duration-slow) ease-soft data-[state=hidden]:opacity-0 data-[state=visible]:opacity-100',
        orientation === 'vertical' ? 'h-full w-2.5' : 'h-2.5 flex-col',
      )}
    >
      <ScrollAreaPrimitive.Thumb className="relative flex-1 rounded-full bg-(--scrollbar-thumb) transition-colors duration-(--duration-base) hover:bg-(--scrollbar-thumb-hover) before:absolute before:top-1/2 before:left-1/2 before:size-full before:min-h-6 before:min-w-6 before:-translate-x-1/2 before:-translate-y-1/2" />
    </ScrollAreaPrimitive.Scrollbar>
  )
}
