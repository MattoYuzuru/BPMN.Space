import { isAcceptedFile } from '@/entities/source'

/** Что нужно сценарию «Новый проект» от сервера: каждый шаг — отдельный запрос. */
export interface CreateFlowDeps {
  createProject: (body: { title: string }) => Promise<{ id: string; title: string }>
  addText: (
    projectId: string,
    body: { kind: 'text'; title: string; content: string },
  ) => Promise<unknown>
  uploadFile: (projectId: string, file: File) => Promise<unknown>
  startBuild: (projectId: string) => Promise<unknown>
  /** Свежее состояние проекта: нужны только статусы источников. */
  fetchProject: (projectId: string) => Promise<{ sources: { status: string }[] }>
  /** Как ждём разбор документов; по умолчанию раз в секунду, не дольше минуты. */
  poll?: { intervalMs: number; timeoutMs: number }
}

export interface CreateFlowInput {
  title: string
  /** Описание процесса: станет первым текстовым источником. */
  description: string
  files: File[]
  /** Проект создаётся в обучении: только для логов, на сервер не уходит. */
  onboarding?: boolean
  /** Отмена ожидания разбора документов (проект к этому моменту уже создан). */
  signal?: AbortSignal
}

export interface CreateFlowResult {
  projectId: string
  title: string
  /** Сколько источников добавлено. */
  sources: number
  /** Запущена ли сборка схемы. */
  building: boolean
  /** Документы не успели разобраться за отведённое время: сборка не запущена, её запустят позже. */
  waitTimedOut: boolean
  /** Что не получилось после создания проекта — для одного итогового уведомления. */
  failures: string[]
}

export const DESCRIPTION_SOURCE_TITLE = 'Описание процесса'

const DEFAULT_POLL = { intervalMs: 1000, timeoutMs: 60_000 }

type WaitOutcome = 'ready' | 'timeout' | 'aborted'

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal?.aborted) return resolve()
    const done = () => {
      clearTimeout(timer)
      signal?.removeEventListener('abort', done)
      resolve()
    }
    const timer = setTimeout(done, ms)
    signal?.addEventListener('abort', done)
  })
}

/**
 * Ждём, пока ни один источник не в обработке: .docx и .pdf после загрузки разбираются в фоне, а
 * сборка берёт только готовые. Ошибка запроса состояния — временная, пробуем снова до лимита.
 */
async function waitForProcessing(
  projectId: string,
  deps: CreateFlowDeps,
  signal?: AbortSignal,
): Promise<WaitOutcome> {
  const { intervalMs, timeoutMs } = deps.poll ?? DEFAULT_POLL
  const attempts = Math.max(1, Math.ceil(timeoutMs / Math.max(intervalMs, 1)))
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    if (signal?.aborted) return 'aborted'
    try {
      const project = await deps.fetchProject(projectId)
      if (!project.sources.some((source) => source.status === 'processing')) return 'ready'
    } catch {
      // Временный сбой сети: следующая попытка.
    }
    await sleep(intervalMs, signal)
  }
  return signal?.aborted ? 'aborted' : 'timeout'
}

/**
 * Проект из названия, описания и файлов: создать -> добавить текст -> загрузить файлы ->
 * дождаться разбора документов -> запустить сборку, если появился хотя бы один источник. Ошибка создания проекта выбрасывается
 * (проекта нет, форма остаётся). Позже проект уже существует, поэтому сбои шагов не прерывают
 * сценарий, а собираются в `failures`: пользователь попадёт в проект и увидит, что осталось.
 */
export async function runCreateFlow(
  input: CreateFlowInput,
  deps: CreateFlowDeps,
): Promise<CreateFlowResult> {
  const project = await deps.createProject({ title: input.title })
  const result: CreateFlowResult = {
    projectId: project.id,
    title: project.title,
    sources: 0,
    building: false,
    waitTimedOut: false,
    failures: [],
  }

  const description = input.description.trim()
  if (description) {
    try {
      await deps.addText(project.id, {
        kind: 'text',
        title: DESCRIPTION_SOURCE_TITLE,
        content: description,
      })
      result.sources += 1
    } catch {
      result.failures.push('описание не добавлено')
    }
  }

  let uploaded = 0
  for (const file of input.files) {
    if (!isAcceptedFile(file.name)) {
      result.failures.push(`формат «${file.name}» не поддерживается`)
      continue
    }
    try {
      await deps.uploadFile(project.id, file)
      result.sources += 1
      uploaded += 1
    } catch {
      result.failures.push(`«${file.name}» не загружен`)
    }
  }

  if (uploaded > 0) {
    const outcome = await waitForProcessing(project.id, deps, input.signal)
    if (outcome === 'aborted') return result
    if (outcome === 'timeout') {
      result.waitTimedOut = true
      return result
    }
  }

  if (result.sources > 0) {
    try {
      await deps.startBuild(project.id)
      result.building = true
    } catch {
      result.failures.push('схема не запущена')
    }
  }
  return result
}
