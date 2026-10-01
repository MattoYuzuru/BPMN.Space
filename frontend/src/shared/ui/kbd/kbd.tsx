import type { ReactNode } from 'react'
import { cn } from '@/shared/lib/cn'
import { isMacPlatform } from '@/shared/lib/platform'

/** Имена клавиш: `mod` — ⌘ на macOS и Ctrl на остальных системах. */
export type KeyName =
  | 'mod'
  | 'shift'
  | 'alt'
  | 'ctrl'
  | 'enter'
  | 'esc'
  | 'tab'
  | 'space'
  | 'backspace'
  | 'up'
  | 'down'
  | 'left'
  | 'right'
  | (string & {})

const MAC: Record<string, string> = {
  mod: '⌘',
  shift: '⇧',
  alt: '⌥',
  ctrl: '⌃',
  enter: '↵',
  backspace: '⌫',
}
const OTHER: Record<string, string> = {
  mod: 'Ctrl',
  shift: 'Shift',
  alt: 'Alt',
  ctrl: 'Ctrl',
  enter: 'Enter',
  backspace: 'Backspace',
}
const COMMON: Record<string, string> = {
  esc: 'Esc',
  tab: 'Tab',
  space: 'Пробел',
  up: '↑',
  down: '↓',
  left: '←',
  right: '→',
}

export function keyLabel(key: KeyName): string {
  const table = isMacPlatform() ? MAC : OTHER
  return table[key] ?? COMMON[key] ?? (key.length === 1 ? key.toUpperCase() : key)
}

const keyClass =
  'inline-flex h-5 min-w-5 items-center justify-center rounded-xs border border-border bg-surface px-1 font-mono text-2xs font-medium leading-none text-fg-muted shadow-[0_1px_0_var(--color-border)]'

export interface KbdProps {
  /** Сочетание клавиш: ['mod', 'k'] → ⌘ K. */
  keys?: KeyName[]
  children?: ReactNode
  className?: string
}

/** Клавиша или сочетание клавиш. В подсказках, меню и палитре команд. */
export function Kbd({ keys, children, className }: KbdProps) {
  if (!keys) return <kbd className={cn(keyClass, className)}>{children}</kbd>
  return (
    <kbd className={cn('inline-flex items-center gap-0.5 font-sans', className)}>
      {keys.map((key) => (
        <kbd key={key} className={keyClass}>
          {keyLabel(key)}
        </kbd>
      ))}
    </kbd>
  )
}
