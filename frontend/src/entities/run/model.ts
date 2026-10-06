import type { Schemas } from '@/shared/api/client'
import { formatDuration } from '@/shared/lib/format'
import type { StepItem } from '@/shared/ui'

export type Run = Schemas['Run']
export type RunMode = Schemas['RunMode']
export type RunStage = Schemas['RunStage']
export type RunSummary = Schemas['RunSummary']

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
  status: 'running' | 'succeeded' | 'failed' | 'cancelled'
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
  error: string | null
  /** Последний обработанный номер события: при переподключении история приходит заново. */
  lastEventId: number
  startedAt: number
  finishedAt: number | null
}

export function initialRunView(run: Run, now: number): RunView {
  const finished =
    run.status === 'succeeded' || run.status === 'failed' || run.status === 'cancelled'
  const status: RunView['status'] =
    run.status === 'succeeded' || run.status === 'failed' || run.status === 'cancelled'
      ? run.status
      : 'running'
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
    error: run.error ?? null,
    lastEventId: 0,
    startedAt: Date.parse(run.started_at) || now,
    finishedAt: finished ? now : null,
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
      if (stage === view.stage) return { ...next, progress, label }
      return {
        ...next,
        stage,
        progress,
        label,
        stageFinishedAt: finishStage(view, now),
        stageStartedAt: { ...view.stageStartedAt, [stage]: view.stageStartedAt[stage] ?? now },
      }
    }
    case 'question': {
      const { id, code, status } = event.data.question
      return {
        ...next,
        questions: [...view.questions.filter((item) => item.id !== id), { id, code, status }],
      }
    }
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
      return {
        ...next,
        status: cancelled ? 'cancelled' : failed ? 'failed' : 'succeeded',
        progress: failed || cancelled ? view.progress : 1,
        summary: run.summary ?? view.summary,
        versionId: run.version_id ?? view.versionId,
        warnings: run.warnings?.length ? run.warnings : view.warnings,
        error: failed ? (run.error ?? view.error ?? 'Прогон не завершён') : null,
        stageFinishedAt: failed ? view.stageFinishedAt : finishStage(view, now),
        finishedAt: now,
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
          ? formatDuration(Math.max(finished - started, 1000))
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
