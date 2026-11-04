import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { type ProjectDetail, projectKeys } from '@/entities/project'
import { upsertQuestion } from '@/entities/question'
import {
  fetchRun,
  formatSummary,
  openRunStream,
  RUN_MODE_LABEL,
  type Run,
  type RunEvent,
  useRunStore,
} from '@/entities/run'
import { needsLogin, sessionQueryOptions } from '@/entities/session'
import { cacheVersion, type VersionSummary, versionLabel } from '@/entities/version'
import { emitOnboardingSignal } from '@/shared/lib/onboarding-signals'
import { toast } from '@/shared/ui'

/** Как часто спрашиваем сервер о прогоне, когда поток событий потерян. */
export const RUN_POLL_MS = 5000
/**
 * Лёгкий опрос статуса, пока поток жив: SSE не присылает события об ожидании технического
 * вопроса, поэтому `waiting` узнаём из GET /runs/{id}, а не ждём вечно «running».
 */
export const RUN_STATUS_POLL_MS = 5000
/** Сколько ждём свежий проект перед сигналом об окончании прогона. */
const FINISH_REFETCH_MS = 4000

/**
 * Связывает прогон проекта с данными экрана. Держит SSE до `done`, даже если active_run
 * уже исчез из обновлённого проекта. Незавершённый прогон сохраняется в RunStore:
 * события идут в стор (панель хода) и в кэш запросов — вопросы появляются и решаются вживую,
 * новая версия схемы подхватывается сама. На `done` проект и версии перезапрашиваются.
 */
export function useRunTracker(projectId: string, activeRun: Run | null | undefined) {
  const client = useQueryClient()
  const track = useRunStore((state) => state.track)
  const apply = useRunStore((state) => state.apply)
  const observe = useRunStore((state) => state.observe)
  const unfinishedRunId = useRunStore((state) => {
    const view = state.views[projectId]
    return view?.finishedAt === null ? view.runId : undefined
  })
  const runId = activeRun?.id ?? unfinishedRunId

  // biome-ignore lint/correctness/useExhaustiveDependencies: поток открывается на смену runId
  useEffect(() => {
    if (!runId) return
    if (activeRun) track(activeRun)
    let finished = false
    let built: VersionSummary | undefined
    let disposed = false
    const isCurrentRun = () => !disposed && useRunStore.getState().views[projectId]?.runId === runId
    let poller: ReturnType<typeof setInterval> | undefined
    /** Поток потерян: статус тогда уточняет его собственный опрос, второй не нужен. */
    let streamLost = false
    // Ожидание свежего проекта перед сигналом об окончании: при выходе из эффекта не висит.
    let finishTimer: ReturnType<typeof setTimeout> | undefined
    let releaseFinishWait: (() => void) | undefined
    let running = activeRun
      ? activeRun.status === 'running'
      : Boolean(useRunStore.getState().views[projectId]?.stage)
    emitOnboardingSignal({
      type: 'run.status',
      status: activeRun?.status === 'queued' ? 'queued' : 'running',
      projectId,
    })

    const handle = (event: RunEvent) => {
      if (!isCurrentRun()) return
      apply(projectId, event)
      if (event.type === 'stage' && !running) {
        running = true
        emitOnboardingSignal({ type: 'run.status', status: 'running', projectId })
      }
      switch (event.type) {
        case 'question':
          upsertQuestion(client, projectId, event.data.question)
          break
        case 'version':
          built = event.data.version
          cacheVersion(client, projectId, event.data.version)
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
      if (finished || !isCurrentRun()) return
      finished = true
      clearInterval(poller)
      const refetched = client.invalidateQueries({ queryKey: projectKeys.detail(projectId) })
      void client.invalidateQueries({ queryKey: projectKeys.lists() })
      // Сигнал об окончании — после свежего проекта: по нему обучение считает открытые вопросы.
      void Promise.race([
        refetched,
        new Promise<void>((resolve) => {
          releaseFinishWait = resolve
          finishTimer = setTimeout(resolve, FINISH_REFETCH_MS)
        }),
      ]).then(() => {
        if (useRunStore.getState().views[projectId]?.runId !== run.id) return
        const project = client.getQueryData<ProjectDetail>(projectKeys.detail(projectId))
        emitOnboardingSignal({
          type: 'run.finished',
          status: run.status,
          openQuestions:
            project?.questions.filter((question) => question.status === 'open').length ?? 0,
          hasDiagram: Boolean(project?.latest_version),
          projectId,
        })
      })
      if (run.status !== 'succeeded') return
      const labels = RUN_MODE_LABEL[run.mode]
      const version = built?.id === run.version_id ? built : undefined
      const parts = [run.summary ? formatSummary(run.summary) : null]
      if (run.mode === 'build' && version) parts.push(versionLabel(version))
      toast.success(labels.done, {
        id: `run-${runId}`,
        description: parts.filter(Boolean).join('. '),
      })
    }

    // SSE молчит об ожидании технического вопроса и может задержаться: пока прогон не завершён,
    // раз в несколько секунд уточняем статус и стоимость по GET /runs/{id}. Ожидание — не финал,
    // поэтому поток оставляем открытым, а `done`-обработчик остаётся единственным источником итога.
    const statusPoller = setInterval(() => {
      if (finished || !isCurrentRun()) return
      if (streamLost) return
      const current = useRunStore.getState().views[projectId]
      if (!current || current.finishedAt !== null || current.status === 'waiting') return
      void fetchRun(runId)
        .then((latest) => {
          if (finished || !isCurrentRun()) return
          if (latest.status === 'waiting') observe(latest)
        })
        .catch(() => undefined)
    }, RUN_STATUS_POLL_MS)

    // Сессия закончилась: любой защищённый запрос получит 401, а его общая обработка уведёт на вход.
    const expire = () => void client.invalidateQueries({ queryKey: projectKeys.detail(projectId) })

    const closeStream = openRunStream(
      runId,
      {
        onEvent: handle,
        onSessionExpired: expire,
        onLost: () => {
          if (finished || !isCurrentRun() || poller) return
          streamLost = true
          void client.invalidateQueries({ queryKey: projectKeys.detail(projectId) })
          toast.warning('Связь с прогоном потеряна', {
            description: 'Результат появится, когда прогон завершится.',
          })
          // Поток не восстановить: сами спрашиваем сервер, пока прогон не дойдёт до конца.
          poller = setInterval(() => {
            void fetchRun(runId)
              .then((run) => {
                if (
                  finished ||
                  !isCurrentRun() ||
                  (run.status !== 'succeeded' &&
                    run.status !== 'failed' &&
                    run.status !== 'cancelled')
                )
                  return
                const last = useRunStore.getState().views[projectId]?.lastEventId ?? 0
                apply(projectId, { type: 'done', id: last + 1, data: { run } })
                finish(run)
              })
              .catch(() => undefined)
          }, RUN_POLL_MS)
        },
      },
      {
        checkSession: async () =>
          !needsLogin(await client.fetchQuery({ ...sessionQueryOptions, staleTime: 0 })),
      },
    )
    return () => {
      disposed = true
      closeStream()
      clearInterval(poller)
      clearInterval(statusPoller)
      clearTimeout(finishTimer)
      releaseFinishWait?.()
    }
  }, [runId, projectId])
}
