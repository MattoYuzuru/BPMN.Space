import { useMutation, useQueryClient } from '@tanstack/react-query'
import { type ProjectDetail, patchProjectInLists, projectKeys } from '@/entities/project'
import { api, errorMessage, unwrap } from '@/shared/api/client'
import { emitOnboardingSignal } from '@/shared/lib/onboarding-signals'
import { toast } from '@/shared/ui'
import type { RunMode } from './model'
import { useRunStore } from './store'

/** Запустить прогон (без кэша и уведомлений — для составных сценариев). */
export async function startRun(projectId: string, mode: RunMode) {
  return unwrap(
    await api.POST('/api/v1/projects/{project_id}/runs', {
      params: { path: { project_id: projectId } },
      body: { mode },
    }),
  )
}

/** Состояние прогона по id: опрос, когда поток событий потерян. */
export async function fetchRun(runId: string) {
  return unwrap(await api.GET('/api/v1/runs/{run_id}', { params: { path: { run_id: runId } } }))
}

/**
 * Запуск прогона. Сразу кладём прогон в проект (active_run, статус) и в стор — панель хода
 * открывается без ожидания следующего запроса, а SSE-подписка стартует по active_run.
 */
export function useStartRun(projectId: string) {
  const client = useQueryClient()
  const track = useRunStore((state) => state.track)
  return useMutation({
    mutationFn: (mode: RunMode) => startRun(projectId, mode),
    onSuccess: (run) => {
      const status = run.mode === 'build' ? 'building' : 'analyzing'
      client.setQueryData<ProjectDetail>(
        projectKeys.detail(projectId),
        (project) => project && { ...project, active_run: run, status },
      )
      patchProjectInLists(client, projectId, (project) => ({ ...project, status }))
      track(run)
      emitOnboardingSignal({ type: 'run.started', id: run.id, projectId })
    },
    onError: (error) =>
      toast.error('Прогон не запущен', { description: errorMessage(error), duration: 8000 }),
  })
}
