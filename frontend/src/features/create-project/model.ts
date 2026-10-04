import { create } from 'zustand'

export type CreateMode = 'blank' | 'example'

/** Как открыть диалог. Всё, кроме `mode`, — нейтральные точки расширения (их использует обучение). */
export interface CreateProjectOpenOptions {
  mode?: CreateMode
  /** Начальное название нового проекта. */
  title?: string
  /** Спрятать переключатель «Пустой / Из примера»: режим зафиксирован. */
  lockMode?: boolean
  /** Минимальная форма: без «Описания процесса» и «Документов» (сборка схемы сама не стартует). */
  minimal?: boolean
  /** Проект создаётся в обучении; только для логов, на сервер не уходит. */
  onboarding?: boolean
}

/** Подмена параметров открытия: возвращает итоговые параметры или `undefined` (без изменений). */
export type CreateProjectOpenInterceptor = (
  options: CreateProjectOpenOptions,
) => CreateProjectOpenOptions | undefined

interface CreateProjectState {
  open: boolean
  /** Диалог уже открывали: код загружен, держим смонтированным ради плавного закрытия. */
  loaded: boolean
  mode: CreateMode
  title: string
  lockMode: boolean
  minimal: boolean
  onboarding: boolean
  /** Подмена параметров для открытия из любого места (кнопки, палитра, 404). */
  interceptor: CreateProjectOpenInterceptor | null
  /** Открыть с параметрами; перед открытием их пропускает `interceptor`. */
  openWith: (options?: CreateProjectOpenOptions) => void
  show: (mode?: CreateMode) => void
  setOpen: (open: boolean) => void
  setMode: (mode: CreateMode) => void
  setInterceptor: (interceptor: CreateProjectOpenInterceptor | null) => void
}

/** Диалог создания проекта один на приложение: его открывают список, палитра команд и 404. */
export const useCreateProjectDialog = create<CreateProjectState>((set, get) => ({
  open: false,
  loaded: false,
  mode: 'blank',
  title: '',
  lockMode: false,
  minimal: false,
  onboarding: false,
  interceptor: null,
  openWith: (options = {}) => {
    const resolved = get().interceptor?.(options) ?? options
    set({
      open: true,
      loaded: true,
      mode: resolved.mode ?? 'blank',
      title: resolved.title ?? '',
      lockMode: resolved.lockMode ?? false,
      minimal: resolved.minimal ?? false,
      onboarding: resolved.onboarding ?? false,
    })
  },
  show: (mode = 'blank') => get().openWith({ mode }),
  setOpen: (open) => set({ open }),
  setMode: (mode) => set({ mode }),
  setInterceptor: (interceptor) => set({ interceptor }),
}))
