import { Tabs as TabsPrimitive } from 'radix-ui'
import { type ComponentProps, useRef } from 'react'
import { cn } from '@/shared/lib/cn'
import { Icon, type IconName } from '../icon'
import { useActiveIndicator } from './use-active-indicator'

export const Tabs = TabsPrimitive.Root

/** Ряд вкладок с тонкой линией-бегунком под активной. */
export function TabsList({
  className,
  children,
  ...props
}: ComponentProps<typeof TabsPrimitive.List>) {
  const ref = useRef<HTMLDivElement>(null)
  const indicator = useActiveIndicator(ref, '[role="tab"][data-state="active"]')
  return (
    <TabsPrimitive.List
      ref={ref}
      className={cn('relative flex items-center gap-1 border-b border-border', className)}
      {...props}
    >
      {children}
      <span
        aria-hidden="true"
        className={cn(
          'pointer-events-none absolute top-0 left-0 transition-[transform,width,opacity] duration-(--duration-slow) ease-soft',
          indicator.visible ? 'opacity-100' : 'opacity-0',
        )}
        style={indicator.style}
      >
        <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-fg" />
      </span>
    </TabsPrimitive.List>
  )
}

export interface TabsTriggerProps extends ComponentProps<typeof TabsPrimitive.Trigger> {
  icon?: IconName
  /** Счётчик справа от подписи: открытые вопросы, источники. */
  count?: number
}

export function TabsTrigger({ icon, count, className, children, ...props }: TabsTriggerProps) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        'group/tab relative z-10 -mb-px flex h-9 cursor-pointer items-center px-0 text-sm font-medium text-fg-muted outline-none',
        'transition-colors duration-(--duration-base) ease-soft hover:text-fg data-[state=active]:text-fg',
        'disabled:pointer-events-none disabled:opacity-45',
        className,
      )}
      {...props}
    >
      <span className="flex items-center gap-1.5 rounded-sm px-2 py-1 outline-focus-ring transition-colors duration-(--duration-base) group-hover/tab:bg-hover group-focus-visible/tab:outline-2 group-focus-visible/tab:outline-solid">
        {icon && <Icon name={icon} size={16} />}
        {children}
        {count !== undefined && (
          <span
            data-numeric
            className="min-w-4 rounded-xs bg-pressed px-1 text-center text-2xs leading-4 text-fg-muted"
          >
            {count}
          </span>
        )}
      </span>
    </TabsPrimitive.Trigger>
  )
}

export function TabsContent({ className, ...props }: ComponentProps<typeof TabsPrimitive.Content>) {
  return (
    <TabsPrimitive.Content
      className={cn('pt-4 outline-none data-[state=active]:animate-fade-in', className)}
      {...props}
    />
  )
}
