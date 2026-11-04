import { useMutation, useQueryClient } from '@tanstack/react-query'
import { cachedModelCapabilities, choiceRequest, getModelChoice } from '@/entities/llm-credential'
import { type ProjectDetail, patchProjectInLists, projectKeys } from '@/entities/project'
import { useCurrentUser } from '@/entities/session'
import { ApiError, api, errorMessage, unwrap } from '@/shared/api/client'
import type { components } from '@/shared/api/schema.gen'
import { emitOnboardingSignal } from '@/shared/lib/onboarding-signals'
import { toast } from '@/shared/ui'
import type { RunMode } from './model'
import { useRunStore } from './store'

/** Явное перестроение сохраняет историю и требует голову, подтверждённую пользователем. */
type RunOptions = Partial<
  Pick<
    components['schemas']['RunCreate'],
    'base_version_id' | 'replace_manual' | 'credential_id' | 'model' | 'profile'
  >
>

export type StartRunInput =
  | RunMode
  | ({ mode: RunMode } & RunOptions & {
        /** Бюджет в долларах и/или токенах: уходит в `RunCreate.profile.budget`. */
        budget?: components['schemas']['RunBudget'] | null
        /** Режим RFC-0004: true — агентный, false — конвейер; не задан — серверное умолчание. */
        agentMode?: boolean
        /** Лимит ходов агента; уходит только с `agentMode=true`. */
        maxSteps?: number | null
      })

/** Запустить прогон (без кэша и уведомлений — для составных сценариев). */
export async function startRun(projectId: string, mode: RunMode, options: RunOptions = {}) {
  return unwrap(
    await api.POST('/api/v1/projects/{project_id}/runs', {
      params: { path: { project_id: projectId } },
      body: { mode, ...options, replace_manual: options.replace_manual ?? false },
    }),
  )
}

/** Состояние прогона по id: опрос, когда поток событий потерян. */
export async function fetchRun(runId: string) {
  return unwrap(await api.GET('/api/v1/runs/{run_id}', { params: { path: { run_id: runId } } }))
}

/** Отменить прогон проекта; остальные редакторы получают завершение по SSE и WebSocket. */
export async function cancelRun(runId: string) {
  return unwrap(
    await api.POST('/api/v1/runs/{run_id}/cancel', { params: { path: { run_id: runId } } }),
  )
}

/**
 * Оценка до запуска (RFC-0005, шаг 4): запросы, токены, деньги и длительность диапазоном.
 * Не создаёт прогон: POST /projects/{id}/runs/estimate.
 */
export async function estimateRun(
  projectId: string,
  body: components['schemas']['RunEstimateRequest'],
) {
  return unwrap(
    await api.POST('/api/v1/projects/{project_id}/runs/estimate', {
      params: { path: { project_id: projectId } },
      body,
    }),
  )
}

/** Оценка стоимости: мутация, потому что это POST; вызывается при открытии диалога и смене профиля. */
export function useRunEstimate(projectId: string) {
  return useMutation({
    mutationFn: (body: components['schemas']['RunEstimateRequest']) => estimateRun(projectId, body),
  })
}

/** Продолжить прогон, ждущий действия по техническому вопросу (`waiting` → `queued`). */
export async function resumeRun(runId: string) {
  return unwrap(
    await api.POST('/api/v1/runs/{run_id}/resume', { params: { path: { run_id: runId } } }),
  )
}

/** Продолжение ждущего прогона: карточка хода снова показывает этапы, проект перечитывается. */
export function useResumeRun(projectId: string) {
  const client = useQueryClient()
  const resume = useRunStore((state) => state.resume)
  return useMutation({
    mutationFn: resumeRun,
    onSuccess: (run) => {
      resume(run)
      return client.invalidateQueries({ queryKey: projectKeys.detail(projectId) })
    },
    onError: (error) => {
      toast.error('Не удалось продолжить прогон', { description: errorMessage(error) })
    },
  })
}

/**
 * Запуск прогона. Сразу кладём прогон в проект (active_run, статус) и в стор — панель хода
 * открывается без ожидания следующего запроса, а SSE-подписка стартует по active_run.
 */
export function useStartRun(projectId: string) {
  const client = useQueryClient()
  const track = useRunStore((state) => state.track)
  const user = useCurrentUser()
  return useMutation({
    // Выбранные пользователем ключ, модель и уровень идут в каждый запуск (анализ и сборка);
    // не выбраны — решает сервер. Бюджет приходит из диалога оценки и дополняет профиль.
    mutationFn: (input: StartRunInput) => {
      const picked = getModelChoice(user?.id)
      const caps = picked && cachedModelCapabilities(client, picked.credentialId, picked.model)
      const choice = choiceRequest(picked, caps || undefined)
      if (typeof input === 'string') return startRun(projectId, input, choice)
      const { budget, agentMode, maxSteps, ...rest } = input
      const modeProfile =
        agentMode === undefined
          ? {}
          : agentMode
            ? { mode: 'agent' as const, ...(maxSteps ? { max_steps: maxSteps } : {}) }
            : { mode: 'pipeline' as const }
      const profile = {
        ...(choice.profile ?? {}),
        ...modeProfile,
        ...(budget ? { budget } : {}),
      }
      const hasProfile = Object.keys(profile).length > 0
      return startRun(projectId, rest.mode, {
        ...rest,
        ...(hasProfile ? { profile } : {}),
      })
    },
    onSuccess: (run) => {
      const status = run.mode === 'build' ? 'building' : 'analyzing'
      client.setQueryData<ProjectDetail>(
        projectKeys.detail(projectId),
        (project) => project && { ...project, active_run: run, status },
      )
      patchProjectInLists(client, projectId, (project) => ({ ...project, status }))
      track(run, true)
      emitOnboardingSignal({ type: 'run.started', id: run.id, projectId })
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) {
        void client.invalidateQueries({ queryKey: projectKeys.detail(projectId) })
      }
      toast.error('Прогон не запущен', { description: errorMessage(error), duration: 8000 })
    },
  })
}
