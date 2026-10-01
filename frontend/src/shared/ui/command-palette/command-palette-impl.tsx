import { Command } from 'cmdk'
import { Dialog as DialogPrimitive, VisuallyHidden } from 'radix-ui'
import { cn } from '@/shared/lib/cn'
import { overlayClass } from '../dialog/dialog'
import { Icon } from '../icon'
import { Kbd } from '../kbd/kbd'
import { menuItem } from '../styles'
import type { CommandPaletteProps } from './types'

/** Реализация палитры команд. Грузится лениво — cmdk не попадает в стартовый бандл. */
export default function CommandPaletteImpl({
  open,
  onOpenChange,
  groups,
  placeholder = 'Найти команду или перейти',
  emptyText = 'Ничего не найдено',
}: CommandPaletteProps) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className={overlayClass} />
        <DialogPrimitive.Content
          aria-describedby={undefined}
          className={cn(
            'motion-dialog fixed inset-x-0 top-[14vh] z-50 mx-auto w-[min(40rem,calc(100vw-2rem))]',
            'overflow-hidden rounded-lg border border-border bg-surface-raised text-fg shadow-lg outline-none',
          )}
        >
          <VisuallyHidden.Root>
            <DialogPrimitive.Title>Палитра команд</DialogPrimitive.Title>
          </VisuallyHidden.Root>
          <Command loop label="Палитра команд" className="flex flex-col">
            <div className="flex items-center gap-2.5 border-b border-border px-4">
              <Icon name="search" className="text-fg-subtle" />
              <Command.Input
                autoFocus
                placeholder={placeholder}
                className="h-12 min-w-0 flex-1 bg-transparent text-base text-fg outline-none placeholder:text-fg-subtle"
              />
              <Kbd keys={['esc']} />
            </div>
            <Command.List className="h-(--cmdk-list-height) max-h-[min(24rem,56vh)] scroll-py-1.5 overflow-y-auto transition-[height] [&_[cmdk-list-sizer]]:p-1.5 duration-base ease-soft">
              <Command.Empty className="py-10 text-center text-sm text-fg-muted">
                {emptyText}
              </Command.Empty>
              {groups.map((group) => (
                <Command.Group
                  key={group.heading}
                  heading={group.heading}
                  className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:type-caption [&_[cmdk-group-heading]]:text-fg-subtle"
                >
                  {group.items.map((item) => (
                    <Command.Item
                      key={item.id}
                      value={`${item.label} ${item.id}`}
                      keywords={item.keywords}
                      disabled={item.disabled}
                      onSelect={() => {
                        onOpenChange(false)
                        item.onSelect()
                      }}
                      className={cn(menuItem, 'h-9')}
                    >
                      {item.icon && <Icon name={item.icon} className="text-fg-muted" />}
                      <span className="flex-1 truncate">{item.label}</span>
                      {item.shortcut && <Kbd keys={item.shortcut} />}
                    </Command.Item>
                  ))}
                </Command.Group>
              ))}
            </Command.List>
          </Command>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}
