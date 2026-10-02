import { create } from 'zustand'

export type CreateMode = 'blank' | 'example'

interface CreateProjectState {
  open: boolean
  mode: CreateMode
  show: (mode?: CreateMode) => void
  setOpen: (open: boolean) => void
  setMode: (mode: CreateMode) => void
}

/** Диалог создания проекта один на приложение: его открывают список, палитра команд и 404. */
export const useCreateProjectDialog = create<CreateProjectState>((set) => ({
  open: false,
  mode: 'blank',
  show: (mode = 'blank') => set({ open: true, mode }),
  setOpen: (open) => set({ open }),
  setMode: (mode) => set({ mode }),
}))
