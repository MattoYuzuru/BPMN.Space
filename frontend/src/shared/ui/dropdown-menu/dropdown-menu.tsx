import { DropdownMenu as MenuPrimitive } from 'radix-ui'
import type { ComponentProps } from 'react'
import { cn } from '@/shared/lib/cn'
import { Icon, type IconName } from '../icon'
import { Kbd, type KeyName } from '../kbd/kbd'
import { floatingSurface, menuItem, menuLabel, menuSeparator } from '../styles'

export const DropdownMenu = MenuPrimitive.Root
export const DropdownMenuTrigger = MenuPrimitive.Trigger
export const DropdownMenuGroup = MenuPrimitive.Group
export const DropdownMenuRadioGroup = MenuPrimitive.RadioGroup
export const DropdownMenuSub = MenuPrimitive.Sub

export function DropdownMenuContent({
  className,
  sideOffset = 6,
  align = 'start',
  ...props
}: ComponentProps<typeof MenuPrimitive.Content>) {
  return (
    <MenuPrimitive.Portal>
      <MenuPrimitive.Content
        sideOffset={sideOffset}
        align={align}
        collisionPadding={8}
        className={cn(floatingSurface, 'min-w-48 rounded-md p-1', className)}
        {...props}
      />
    </MenuPrimitive.Portal>
  )
}

interface ItemExtras {
  icon?: IconName
  shortcut?: KeyName[]
  /** danger — для удаления и других необратимых действий. */
  tone?: 'default' | 'danger'
}

export function DropdownMenuItem({
  icon,
  shortcut,
  tone = 'default',
  className,
  children,
  ...props
}: ComponentProps<typeof MenuPrimitive.Item> & ItemExtras) {
  return (
    <MenuPrimitive.Item
      className={cn(
        menuItem,
        tone === 'danger' && 'text-danger-fg data-[highlighted]:bg-danger-subtle',
        className,
      )}
      {...props}
    >
      {icon && (
        <Icon
          name={icon}
          size={16}
          className={tone === 'danger' ? 'text-danger-fg' : 'text-fg-muted'}
        />
      )}
      <span className="flex-1 truncate">{children}</span>
      {shortcut && <Kbd keys={shortcut} className="ml-4" />}
    </MenuPrimitive.Item>
  )
}

export function DropdownMenuCheckboxItem({
  className,
  children,
  ...props
}: ComponentProps<typeof MenuPrimitive.CheckboxItem>) {
  return (
    <MenuPrimitive.CheckboxItem className={cn(menuItem, 'pl-8', className)} {...props}>
      <span className="flex-1 truncate">{children}</span>
      <MenuPrimitive.ItemIndicator className="absolute left-2 inline-flex text-accent-fg">
        <Icon name="check" size={14} />
      </MenuPrimitive.ItemIndicator>
    </MenuPrimitive.CheckboxItem>
  )
}

export function DropdownMenuRadioItem({
  className,
  children,
  ...props
}: ComponentProps<typeof MenuPrimitive.RadioItem>) {
  return (
    <MenuPrimitive.RadioItem className={cn(menuItem, 'pl-8', className)} {...props}>
      <span className="flex-1 truncate">{children}</span>
      <MenuPrimitive.ItemIndicator className="absolute left-2 inline-flex text-accent-fg">
        <Icon name="check" size={14} />
      </MenuPrimitive.ItemIndicator>
    </MenuPrimitive.RadioItem>
  )
}

export function DropdownMenuLabel({
  className,
  ...props
}: ComponentProps<typeof MenuPrimitive.Label>) {
  return <MenuPrimitive.Label className={cn(menuLabel, className)} {...props} />
}

export function DropdownMenuSeparator({
  className,
  ...props
}: ComponentProps<typeof MenuPrimitive.Separator>) {
  return <MenuPrimitive.Separator className={cn(menuSeparator, className)} {...props} />
}

export function DropdownMenuSubTrigger({
  icon,
  className,
  children,
  ...props
}: ComponentProps<typeof MenuPrimitive.SubTrigger> & { icon?: IconName }) {
  return (
    <MenuPrimitive.SubTrigger
      className={cn(menuItem, 'data-[state=open]:bg-hover', className)}
      {...props}
    >
      {icon && <Icon name={icon} size={16} className="text-fg-muted" />}
      <span className="flex-1 truncate">{children}</span>
      <Icon name="chevron-right" size={14} className="text-fg-subtle" />
    </MenuPrimitive.SubTrigger>
  )
}

export function DropdownMenuSubContent({
  className,
  ...props
}: ComponentProps<typeof MenuPrimitive.SubContent>) {
  return (
    <MenuPrimitive.Portal>
      <MenuPrimitive.SubContent
        sideOffset={4}
        collisionPadding={8}
        className={cn(floatingSurface, 'min-w-44 rounded-md p-1', className)}
        {...props}
      />
    </MenuPrimitive.Portal>
  )
}
