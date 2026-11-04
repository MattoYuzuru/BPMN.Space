import type { Schemas } from '@/shared/api/client'
import { formatDuration } from '@/shared/lib/format'
import type { StepItem } from '@/shared/ui'

export type Run = Schemas['Run']
export type RunMode = Schemas['RunMode']
export type RunStage = Schemas['RunStage']
export type RunSummary = Schemas['RunSummary']
export type RunCost = Schemas['RunCost']
export type RunBudget = Schemas['RunBudget']
export type RunEstimate = Schemas['RunEstimate']
export type StageCost = Schemas['StageCost']
export type RunProfile = NonNullable<Schemas['Run']['profile']>
export type RunProfileMode = NonNullable<RunProfile['mode']>

/** Агентный режим RFC-0004: `RunCreate.profile.mode`. */
export const AGENT_MODE = 'agent' as const
export const PIPELINE_MODE = 'pipeline' as const
/** Пресеты лимита ходов агента; серверный потолок может быть меньше — 422 объясняется в диалоге. */
export const AGENT_STEP_PRESETS = [6, 12, 24] as const
export const DEFAULT_AGENT_MAX_STEPS = 12

/** Этапы прогона по режимам (RFC §5.1, docs/backend/mock.md). */
export const STAGES: Record<RunMode, readonly RunStage[]> = {
  analyze: ['reading_sources', 'extracting', 'reconciling'],
  build: ['reading_sources', 'extracting', 'reconciling', 'structuring', 'validating', 'layout'],
}

/** Подписи этапов до прихода события (сервер присылает те же в `stage.label`). */
export const STAGE_LABEL: Record<RunStage, string> = {
  reading_sources: 'Читаю источники',
  extracting: 'Ищу участников и шаги',
  reconciling: 'Сверяю вопросы',
  structuring: 'Строю структуру процесса',
  validating: 'Проверяю схему',
  layout: 'Раскладываю схему',
}

export const RUN_MODE_LABEL: Record<RunMode, { title: string; done: string }> = {
  analyze: { title: 'Анализ', done: 'Анализ завершён' },
  build: { title: 'Сборка схемы', done: 'Схема построена' },
}

/** Событие SSE после разбора: тип из поля `event:`, номер из `id:`, данные из `data:`. */
export type RunEvent =
  | { type: 'stage'; id: number; data: Schemas['StageEventData'] }
  | { type: 'question'; id: number; data: Schemas['QuestionEventData'] }
  | { type: 'usage'; id: number; data: RunCost }
  | { type: 'summary'; id: number; data: RunSummary }
  | { type: 'version'; id: number; data: Schemas['VersionEventData'] }
  | { type: 'error'; id: number; data: Schemas['ErrorEventData'] }
  | { type: 'done'; id: number; data: Schemas['DoneEventData'] }

export type RunEventType = RunEvent['type']

export interface TouchedQuestion {
  id: string
  code: string
  status: Schemas['QuestionStatus']
}

/** Состояние прогона на экране: собирается из событий SSE редьюсером reduceRun. */
export interface RunView {
  runId: string
  projectId: string
  mode: RunMode
  /** `waiting` — прогон ждёт действия по блокирующему техническому вопросу (RFC-0006). */
  status: 'running' | 'waiting' | 'succeeded' | 'failed' | 'cancelled'
  stage: RunStage | null
  progress: number
  label: string
  /** Время начала и конца этапов (мс) — для длительностей в Stepper. */
  stageStartedAt: Partial<Record<RunStage, number>>
  stageFinishedAt: Partial<Record<RunStage, number>>
  summary: RunSummary | null
  /** Вопросы, которые прогон изменил или создал. */
  questions: TouchedQuestion[]
  versionId: string | null
  /** Предупреждения прогона: например, часть источников не поместилась в контекст модели. */
  warnings: string[]
  /** Потрачено по журналу вызовов модели; null — вызовов ещё не было. */
  cost: RunCost | null
  /** Бюджет прогона из профиля запуска. */
  budget: RunBudget | null
  /** Режим из `Run.profile.mode`: конвейер или агент (RFC-0004). */
  profileMode: RunProfileMode
  /** Лимит ходов агента из `Run.profile.max_steps`; null — пайплайн/не задан. */
  maxSteps: number | null
  error: string | null
  /** Последний обработанный номер события: при переподключении история приходит заново. */
  lastEventId: number
  startedAt: number
  finishedAt: number | null
}

export function runStatusView(status: Schemas['RunStatus']): RunView['status'] {
  if (status === 'succeeded' || status === 'failed' || status === 'cancelled') return status
  if (status === 'waiting') return 'waiting'
  return 'running'
}

export function initialRunView(run: Run, now: number): RunView {
  const finished =
    run.status === 'succeeded' || run.status === 'failed' || run.status === 'cancelled'
  const status = runStatusView(run.status)
  return {
    runId: run.id,
    projectId: run.project_id,
    mode: run.mode,
    status,
    stage: run.stage,
    progress: run.progress,
    label: run.stage_label,
    stageStartedAt: run.stage ? { [run.stage]: now } : {},
    stageFinishedAt: {},
    summary: run.summary ?? null,
    questions: [],
    versionId: run.version_id ?? null,
    warnings: run.warnings ?? [],
    cost: run.cost ?? null,
    budget: run.profile?.budget ?? null,
    profileMode: run.profile?.mode ?? PIPELINE_MODE,
    maxSteps: run.profile?.max_steps ?? null,
    error: run.error ?? null,
    lastEventId: 0,
    startedAt: Date.parse(run.started_at) || now,
    finishedAt: finished ? Date.parse(run.finished_at ?? '') || now : null,
  }
}

function finishStage(view: RunView, now: number): RunView['stageFinishedAt'] {
  if (!view.stage || view.stageFinishedAt[view.stage]) return view.stageFinishedAt
  return { ...view.stageFinishedAt, [view.stage]: now }
}

/**
 * Редьюсер событий прогона. Идемпотентен: событие с номером не больше уже обработанного
 * игнорируется — поэтому переподключение, при котором сервер шлёт историю заново, безопасно.
 */
export function reduceRun(view: RunView, event: RunEvent, now: number): RunView {
  if (event.id > 0 && event.id <= view.lastEventId) return view
  const next: RunView = { ...view, lastEventId: Math.max(view.lastEventId, event.id) }
  switch (event.type) {
    case 'stage': {
      const { stage, progress, label } = event.data
      const status = view.status === 'waiting' ? 'running' : view.status
      if (stage === view.stage) return { ...next, progress, label, status }
      return {
        ...next,
        status,
        stage,
        progress,
        label,
        stageFinishedAt: finishStage(view, now),
        stageStartedAt: { ...view.stageStartedAt, [stage]: view.stageStartedAt[stage] ?? now },
      }
    }
    case 'question': {
      const question = event.data.question
      const { id, code, status } = question
      // Блокирующий технический вопрос переводит прогон в `waiting`; SSE остаётся открытым.
      const waiting =
        question.category === 'technical' && question.blocking && question.status === 'open'
      return {
        ...next,
        status: waiting ? 'waiting' : view.status === 'waiting' ? 'running' : view.status,
        questions: [...view.questions.filter((item) => item.id !== id), { id, code, status }],
      }
    }
    case 'usage':
      return { ...next, cost: event.data }
    case 'summary':
      return { ...next, summary: event.data }
    case 'version':
      return { ...next, versionId: event.data.version.id }
    case 'error':
      return { ...next, status: 'failed', error: event.data.message }
    case 'done': {
      const { run } = event.data
      const failed = run.status === 'failed' || view.status === 'failed'
      const cancelled = run.status === 'cancelled' || view.status === 'cancelled'
      // `waiting` — не финал: прогон ждёт действия по техническому вопросу.
      const waiting = run.status === 'waiting'
      return {
        ...next,
        status: waiting ? 'waiting' : cancelled ? 'cancelled' : failed ? 'failed' : 'succeeded',
        progress: waiting ? view.progress : failed || cancelled ? view.progress : 1,
        summary: run.summary ?? view.summary,
        versionId: run.version_id ?? view.versionId,
        warnings: run.warnings?.length ? run.warnings : view.warnings,
        cost: run.cost ?? view.cost,
        budget: run.profile?.budget ?? view.budget,
        profileMode: run.profile?.mode ?? view.profileMode,
        maxSteps: run.profile?.max_steps ?? view.maxSteps,
        error: failed ? (run.error ?? view.error ?? 'Прогон не завершён') : null,
        stageFinishedAt: failed ? view.stageFinishedAt : finishStage(view, now),
        finishedAt: waiting ? null : Date.parse(run.finished_at ?? '') || now,
      }
    }
  }
}

/** Этапы для Stepper: пройденные — с длительностью, текущий — «выполняется», упавший — ошибка. */
export function runSteps(view: RunView): StepItem[] {
  const stages = STAGES[view.mode]
  const currentIndex = view.stage ? stages.indexOf(view.stage) : -1
  return stages.map((stage, index) => {
    let status: StepItem['status'] = 'upcoming'
    if (view.status === 'succeeded') status = 'complete'
    else if (index < currentIndex) status = 'complete'
    else if (index === currentIndex) status = view.status === 'failed' ? 'error' : 'current'
    const started = view.stageStartedAt[stage]
    const finished = view.stageFinishedAt[stage]
    return {
      id: stage,
      title: STAGE_LABEL[stage],
      status,
      description: status === 'error' ? (view.error ?? undefined) : undefined,
      meta:
        status === 'complete' && started !== undefined && finished !== undefined
          ? finished - started < 1000
            ? 'менее 1 с'
            : formatDuration(finished - started)
          : undefined,
    }
  })
}

/** «Решено 2, осталось 2, новых 1» — итог прогона для уведомления. Нули опускаются. */
export function formatSummary(summary: Pick<RunSummary, 'resolved' | 'open' | 'new'>): string {
  const parts = [
    summary.resolved > 0 && `решено ${summary.resolved}`,
    summary.open > 0 && `осталось ${summary.open}`,
    summary.new > 0 && `новых ${summary.new}`,
  ].filter(Boolean) as string[]
  if (parts.length === 0) return 'Открытых вопросов нет'
  const text = parts.join(', ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/** Прогон идёт агентным режимом (RFC-0004). */
export function isAgentRun(view: Pick<RunView, 'profileMode'>): boolean {
  return view.profileMode === AGENT_MODE
}

/**
 * Сколько ходов сделал агент: каждый ход — вызов модели со `stage=agent` в `RunCost.by_stage`.
 * Это реальные данные API; имён инструментов в Run/SSE нет, поэтому UI их не выдумывает.
 */
export function agentSteps(cost: RunCost | null): number {
  return cost?.by_stage?.find((stage) => stage.stage === 'agent')?.calls ?? 0
}
