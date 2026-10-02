import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { projectKeys } from '@/entities/project'
import { upsertQuestion } from '@/entities/question'
import {
  formatSummary,
  openRunStream,
  RUN_MODE_LABEL,
  type Run,
  type RunEvent,
  useRunStore,
} from '@/entities/run'
import { type Version, versionKeys, versionLabel } from '@/entities/version'
import { toast } from '@/shared/ui'

/**
 * Связывает прогон проекта с данными экрана. Пока у проекта есть active_run, держит SSE-поток:
 * события идут в стор (панель хода) и в кэш запросов — вопросы появляются и решаются вживую,
 * новая версия схемы подхватывается сама. На `done` проект и версии перезапрашиваются.
 */
export function useRunTracker(projectId: string, activeRun: Run | null | undefined) {
  const client = useQueryClient()
  const track = useRunStore((state) => state.track)
  const apply = useRunStore((state) => state.apply)
  const runId = activeRun?.id

  // biome-ignore lint/correctness/useExhaustiveDependencies: поток открывается на смену runId
  useEffect(() => {
    if (!activeRun || !runId) return
    track(activeRun)

    const handle = (event: RunEvent) => {
      apply(projectId, event)
      switch (event.type) {
        case 'question':
          upsertQuestion(client, projectId, event.data.question)
          break
        case 'version':
          client.setQueryData<Version[]>(versionKeys.list(projectId), (list) =>
            list ? [event.data.version, ...list] : list,
          )
          break
        case 'error':
          toast.error('Прогон остановился с ошибкой', {
            id: `run-${runId}`,
            description: event.data.message,
            duration: 10_000,
          })
          break
        case 'done':
          finish(event.data.run)
          break
        default:
          break
      }
    }

    const finish = (run: Run) => {
      void client.invalidateQueries({ queryKey: projectKeys.detail(projectId) })
      void client.invalidateQueries({ queryKey: projectKeys.lists() })
      if (run.status !== 'succeeded') return
      const labels = RUN_MODE_LABEL[run.mode]
      const version = client
        .getQueryData<Version[]>(versionKeys.list(projectId))
        ?.find((item) => item.id === run.version_id)
      const parts = [run.summary ? formatSummary(run.summary) : null]
      if (run.mode === 'build' && version) parts.push(versionLabel(version))
      toast.success(labels.done, {
        id: `run-${runId}`,
        description: parts.filter(Boolean).join('. '),
      })
    }

    return openRunStream(runId, {
      onEvent: handle,
      onLost: () => {
        void client.invalidateQueries({ queryKey: projectKeys.detail(projectId) })
        toast.warning('Связь с прогоном потеряна', {
          description: 'Результат появится, когда прогон завершится.',
        })
      },
    })
  }, [runId, projectId])
}
