import { create } from 'zustand'
import { registerAccountReset } from '@/shared/lib/account-reset'
import { rememberRun } from './last-run'
import {
  initialRunView,
  type Run,
  type RunEvent,
  type RunView,
  reduceRun,
  runStatusView,
} from './model'

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
  /** Прогон продолжен после `waiting`: карточка снова показывает ход. */
  resume: (run: Run) => void
  /**
   * Наблюдение за прогоном по опросу (GET /runs/{id}): обновляет статус и стоимость, не трогая
   * номер последнего события — SSE-поток продолжает работать и присылает свои события.
   */
  observe: (run: Run) => void
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
      if (run.status !== 'succeeded' && run.status !== 'failed' && run.status !== 'cancelled') {
        rememberRun(run.project_id, run.id)
      }
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
  observe: (run) =>
    set((state) => {
      const view = state.views[run.project_id]
      if (!view || view.runId !== run.id) return state
      const status = runStatusView(run.status)
      const cost = run.cost ?? view.cost
      const budget = run.profile?.budget ?? view.budget
      const sameCost =
        (cost?.calls ?? 0) === (view.cost?.calls ?? 0) &&
        (cost?.cost_usd ?? null) === (view.cost?.cost_usd ?? null) &&
        (cost?.tokens_in ?? 0) === (view.cost?.tokens_in ?? 0) &&
        (cost?.tokens_out ?? 0) === (view.cost?.tokens_out ?? 0)
      const sameBudget = JSON.stringify(budget) === JSON.stringify(view.budget)
      if (status === view.status && sameCost && sameBudget) return state
      return {
        views: {
          ...state.views,
          [run.project_id]: {
            ...view,
            status,
            cost,
            budget,
            stage: run.stage,
            progress: run.progress,
            label: run.stage_label,
            error: run.error ?? view.error,
          },
        },
      }
    }),
  resume: (run) =>
    set((state) => {
      const view = state.views[run.project_id]
      if (!view || view.runId !== run.id) return state
      return {
        views: {
          ...state.views,
          [run.project_id]: {
            ...view,
            status: 'running',
            stage: run.stage,
            progress: run.progress,
            label: run.stage_label,
            finishedAt: null,
            error: null,
          },
        },
        expanded: { ...state.expanded, [run.project_id]: true },
      }
    }),
  dismiss: (projectId) =>
    set((state) => {
      const { [projectId]: _removed, ...views } = state.views
      const { [projectId]: _expanded, ...expanded } = state.expanded
      const { [projectId]: _presented, ...presented } = state.presented
      return { views, expanded, presented }
    }),
}))

registerAccountReset(() => useRunStore.setState({ views: {}, expanded: {}, presented: {} }))

export function useRunView(projectId: string): RunView | undefined {
  return useRunStore((state) => state.views[projectId])
}
