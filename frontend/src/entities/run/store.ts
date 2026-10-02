import { create } from 'zustand'
import { initialRunView, type Run, type RunEvent, type RunView, reduceRun } from './model'

interface RunStore {
  /** Последний прогон каждого проекта (идущий или только что завершённый). */
  views: Record<string, RunView>
  /** Панель хода прогона развёрнута. */
  expanded: Record<string, boolean>
  track: (run: Run) => void
  apply: (projectId: string, event: RunEvent) => void
  setExpanded: (projectId: string, expanded: boolean) => void
  dismiss: (projectId: string) => void
}

/**
 * Состояние прогонов вне React-дерева: панель хода, шапка и палитра команд читают одно и то же,
 * а сворачивание панелей не теряет ход.
 */
export const useRunStore = create<RunStore>((set) => ({
  views: {},
  expanded: {},
  track: (run) =>
    set((state) => {
      const current = state.views[run.project_id]
      if (current?.runId === run.id) return state
      return {
        views: { ...state.views, [run.project_id]: initialRunView(run, Date.now()) },
        expanded: { ...state.expanded, [run.project_id]: true },
      }
    }),
  apply: (projectId, event) =>
    set((state) => {
      const current = state.views[projectId]
      if (!current) return state
      const next = reduceRun(current, event, Date.now())
      return next === current ? state : { views: { ...state.views, [projectId]: next } }
    }),
  setExpanded: (projectId, expanded) =>
    set((state) => ({ expanded: { ...state.expanded, [projectId]: expanded } })),
  dismiss: (projectId) =>
    set((state) => {
      const { [projectId]: _removed, ...views } = state.views
      return { views }
    }),
}))

export function useRunView(projectId: string): RunView | undefined {
  return useRunStore((state) => state.views[projectId])
}
