import { lazy, Suspense, useEffect, useState } from 'react'
import type { CommandPaletteProps } from './types'

const CommandPaletteImpl = lazy(() => import('./command-palette-impl'))

/** Заранее подгрузить палитру (например, при простое или наведении на кнопку поиска). */
export function preloadCommandPalette() {
  return import('./command-palette-impl')
}

/**
 * Палитра команд (⌘K): поиск по действиям и переходам. Код грузится при первом открытии,
 * после этого остаётся смонтированным, чтобы закрытие было плавным.
 */
export function CommandPalette(props: CommandPaletteProps) {
  const [mounted, setMounted] = useState(props.open)
  useEffect(() => {
    if (props.open) setMounted(true)
  }, [props.open])
  if (!mounted && !props.open) return null
  return (
    <Suspense fallback={null}>
      <CommandPaletteImpl {...props} />
    </Suspense>
  )
}
