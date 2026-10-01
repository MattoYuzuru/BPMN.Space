import { useEffect, useRef } from 'react'
import { isMacPlatform } from '@/shared/lib/platform'

const EDITABLE = 'input, textarea, select, [contenteditable=""], [contenteditable="true"]'

/** Проверяет событие на сочетание: ['mod', 'k'] — ⌘K на macOS и Ctrl+K на остальных. */
export function matchesHotkey(event: KeyboardEvent, keys: readonly string[]): boolean {
  const mac = isMacPlatform()
  const wanted = new Set(keys.map((key) => key.toLowerCase()))
  const mod = wanted.has('mod')
  const needMeta = (mod && mac) || wanted.has('meta')
  const needCtrl = (mod && !mac) || wanted.has('ctrl')
  if (event.metaKey !== needMeta || event.ctrlKey !== needCtrl) return false
  if (event.shiftKey !== wanted.has('shift') || event.altKey !== wanted.has('alt')) return false
  const main = [...wanted].find((key) => !['mod', 'meta', 'ctrl', 'shift', 'alt'].includes(key))
  if (!main) return false
  return event.key.toLowerCase() === main || event.code.toLowerCase() === `key${main}`
}

/**
 * Глобальная горячая клавиша. В полях ввода срабатывает только сочетание с модификатором.
 * Подписи клавиш в интерфейсе — компонент Kbd с теми же именами.
 */
export function useHotkey(
  keys: readonly string[],
  handler: (event: KeyboardEvent) => void,
  { enabled = true }: { enabled?: boolean } = {},
) {
  const handlerRef = useRef(handler)
  handlerRef.current = handler
  const signature = keys.join('+')

  useEffect(() => {
    if (!enabled) return
    const parts = signature.split('+')
    const hasModifier = parts.some((key) => ['mod', 'meta', 'ctrl', 'alt'].includes(key))
    const onKeyDown = (event: KeyboardEvent) => {
      if (!matchesHotkey(event, parts)) return
      const target = event.target as Element | null
      if (!hasModifier && target?.closest?.(EDITABLE)) return
      event.preventDefault()
      handlerRef.current(event)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [signature, enabled])
}
