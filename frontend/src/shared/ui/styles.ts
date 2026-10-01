/**
 * Общие классы дизайн-системы: рамка полей ввода, поверхность всплывающих слоёв, пункт меню.
 * Используются только внутри shared/ui — так поля, селекты и меню выглядят одинаково.
 */
import { cva } from 'class-variance-authority'

/** Рамка поля: Input, Select. Фокус — акцентная граница и мягкое кольцо. */
export const controlFrame = cva(
  [
    'flex w-full items-center rounded-md border border-border bg-surface text-fg shadow-xs',
    'transition-[border-color,box-shadow,background-color] duration-(--duration-base) ease-soft',
    'hover:border-border-strong',
    'focus-within:border-accent focus-within:ring-3 focus-within:ring-accent/15 focus-within:hover:border-accent',
    'data-[invalid]:border-danger data-[invalid]:hover:border-danger data-[invalid]:focus-within:ring-danger/15',
    'data-[disabled]:pointer-events-none data-[disabled]:bg-bg-subtle data-[disabled]:opacity-60',
  ],
  {
    variants: {
      size: {
        sm: 'h-7 gap-1.5 rounded-sm px-2 text-xs',
        md: 'h-8 gap-2 px-2.5 text-sm',
      },
    },
    defaultVariants: { size: 'md' },
  },
)

/** Поверхность меню, селекта, поповера и подсказки. */
export const floatingSurface =
  'z-50 border border-border bg-surface-raised text-fg shadow-md outline-none motion-pop'

/** Пункт меню, селекта и палитры команд. */
export const menuItem = [
  'relative flex h-8 w-full cursor-default select-none items-center gap-2 rounded-xs px-2 text-sm text-fg outline-none',
  'transition-colors duration-(--duration-fast) ease-soft',
  'data-[highlighted]:bg-hover data-[selected=true]:bg-hover',
  'data-[disabled]:pointer-events-none data-[disabled]:opacity-45 data-[disabled=true]:pointer-events-none data-[disabled=true]:opacity-45',
].join(' ')

export const menuLabel = 'px-2 pt-2 pb-1 type-caption text-fg-subtle'
export const menuSeparator = '-mx-1 my-1 h-px bg-border'
