import { create } from 'zustand'
import { initialRunView, type Run, type RunEvent, type RunView, reduceRun } from './model'

interface RunStore {
  /** Последний прогон каждого проекта (идущий или только что завершённый). */
  views: Record<string, RunView>
  /** Панель хода прогона развёрнута. */
  expanded: Record<string, boolean>
  /** Последний прогон, итог которого пользователь уже увидел или закрыл сам. */
  presented: Record<string, string>
  track: (run: Run, startedHere?: boolean) => void
  apply: (projectId: string, event: RunEvent) => void
  setExpanded: (projectId: string, expanded: boolean) => void
  dismiss: (projectId: string) => void
  finishPresentation: (projectId: string, runId: string) => void
}

/**
 * Состояние прогонов вне React-дерева: панель хода, шапка и палитра команд читают одно и то же,
 * а сворачивание панелей не теряет ход.
 */
export const useRunStore = create<RunStore>((set) => ({
  views: {},
  expanded: {},
  presented: {},
  track: (run, startedHere = false) =>
    set((state) => {
      const current = state.views[run.project_id]
      if (current?.runId === run.id) return state
      return {
        views: { ...state.views, [run.project_id]: initialRunView(run, Date.now()) },
        expanded: { ...state.expanded, [run.project_id]: true },
        // Уже завершённый прогон при позднем подключении открывается сразу как итог.
        presented:
          !startedHere &&
          (run.status === 'succeeded' || run.status === 'failed' || run.status === 'cancelled')
            ? { ...state.presented, [run.project_id]: run.id }
            : state.presented,
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
    set((state) => ({
      expanded: { ...state.expanded, [projectId]: expanded },
      // Скрытую пользователем карточку не проигрываем заново при возвращении к итогу.
      presented:
        !expanded && state.views[projectId]
          ? { ...state.presented, [projectId]: state.views[projectId].runId }
          : state.presented,
    })),
  finishPresentation: (projectId, runId) =>
    set((state) =>
      state.views[projectId]?.runId === runId
        ? { presented: { ...state.presented, [projectId]: runId } }
        : state,
    ),
  dismiss: (projectId) =>
    set((state) => {
      const { [projectId]: _removed, ...views } = state.views
      const { [projectId]: _expanded, ...expanded } = state.expanded
      const { [projectId]: _presented, ...presented } = state.presented
      return { views, expanded, presented }
    }),
}))

export function useRunView(projectId: string): RunView | undefined {
  return useRunStore((state) => state.views[projectId])
}
