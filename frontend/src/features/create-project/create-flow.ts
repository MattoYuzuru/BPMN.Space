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
}

export interface CreateFlowInput {
  title: string
  /** Описание процесса: станет первым текстовым источником. */
  description: string
  files: File[]
}

export interface CreateFlowResult {
  projectId: string
  title: string
  /** Сколько источников добавлено. */
  sources: number
  /** Запущена ли сборка схемы. */
  building: boolean
  /** Что не получилось после создания проекта — для одного итогового уведомления. */
  failures: string[]
}

export const DESCRIPTION_SOURCE_TITLE = 'Описание процесса'

/**
 * Проект из названия, описания и файлов: создать -> добавить текст -> загрузить файлы ->
 * запустить сборку, если появился хотя бы один источник. Ошибка создания проекта выбрасывается
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

  for (const file of input.files) {
    if (!isAcceptedFile(file.name)) {
      result.failures.push(`формат «${file.name}» не поддерживается`)
      continue
    }
    try {
      await deps.uploadFile(project.id, file)
      result.sources += 1
    } catch {
      result.failures.push(`«${file.name}» не загружен`)
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
