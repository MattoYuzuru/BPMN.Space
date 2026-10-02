import { useEffect } from 'react'
import { create } from 'zustand'
import type { CommandGroup } from '@/shared/ui'

interface CommandState {
  open: boolean
  /** Группы команд, которые добавили экраны (например, «Проект» на рабочем месте). */
  contextual: Record<string, CommandGroup>
  setOpen: (open: boolean) => void
  register: (id: string, group: CommandGroup) => void
  unregister: (id: string) => void
}

export const useCommandStore = create<CommandState>((set) => ({
  open: false,
  contextual: {},
  setOpen: (open) => set({ open }),
  register: (id, group) => set((state) => ({ contextual: { ...state.contextual, [id]: group } })),
  unregister: (id) =>
    set((state) => {
      const { [id]: _removed, ...contextual } = state.contextual
      return { contextual }
    }),
}))

export function openCommandPalette() {
  useCommandStore.getState().setOpen(true)
}

/**
 * Экран добавляет свои команды в палитру, пока он открыт. Группа пересобирается при каждом
 * изменении `group` — передавайте мемоизированный объект.
 */
export function useRegisterCommands(id: string, group: CommandGroup | null) {
  const register = useCommandStore((state) => state.register)
  const unregister = useCommandStore((state) => state.unregister)
  useEffect(() => {
    if (!group) return
    register(id, group)
    return () => unregister(id)
  }, [id, group, register, unregister])
}
