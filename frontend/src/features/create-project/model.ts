import { create } from 'zustand'

export type CreateMode = 'blank' | 'example'

interface CreateProjectState {
  open: boolean
  /** Диалог уже открывали: код загружен, держим смонтированным ради плавного закрытия. */
  loaded: boolean
  mode: CreateMode
  show: (mode?: CreateMode) => void
  setOpen: (open: boolean) => void
  setMode: (mode: CreateMode) => void
}

/** Диалог создания проекта один на приложение: его открывают список, палитра команд и 404. */
export const useCreateProjectDialog = create<CreateProjectState>((set) => ({
  open: false,
  loaded: false,
  mode: 'blank',
  show: (mode = 'blank') => set({ open: true, loaded: true, mode }),
  setOpen: (open) => set({ open }),
  setMode: (mode) => set({ mode }),
}))
