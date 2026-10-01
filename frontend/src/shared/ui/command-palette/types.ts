import type { IconName } from '../icon'
import type { KeyName } from '../kbd/kbd'

export interface CommandItem {
  id: string
  label: string
  icon?: IconName
  shortcut?: KeyName[]
  /** Дополнительные слова для поиска: синонимы, английские названия. */
  keywords?: string[]
  disabled?: boolean
  onSelect: () => void
}

export interface CommandGroup {
  heading: string
  items: CommandItem[]
}

export interface CommandPaletteProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  groups: CommandGroup[]
  placeholder?: string
  emptyText?: string
}
