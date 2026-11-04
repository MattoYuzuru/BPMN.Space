/**
 * Последний известный прогон проекта в этой сессии. Нужен только для восстановления карточки
 * хода после перезагрузки страницы, если сервер не отдал `active_run` в проекте: по id
 * запрашиваем `GET /runs/{id}` и продолжаем следить. В localStorage не пишем.
 */

const PREFIX = 'arkhitektor:last-run:'

function key(projectId: string) {
  return `${PREFIX}${projectId}`
}

export function rememberRun(projectId: string, runId: string): void {
  try {
    window.sessionStorage.setItem(key(projectId), runId)
  } catch {
    // Приватный режим или отключённое хранилище: без восстановления после перезагрузки.
  }
}

export function rememberedRunId(projectId: string): string | null {
  try {
    return window.sessionStorage.getItem(key(projectId))
  } catch {
    return null
  }
}

export function forgetRun(projectId: string): void {
  try {
    window.sessionStorage.removeItem(key(projectId))
  } catch {
    // Нечего забывать.
  }
}
