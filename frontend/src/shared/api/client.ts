/**
 * Типизированный клиент API v1 (openapi-fetch по schema.gen.ts) и вспомогательные запросы,
 * которые openapi-fetch не покрывает: multipart с ходом загрузки и адрес SSE-потока.
 * Ошибки бэкенда — `{"detail": "…"}` на русском; наружу выходят как ApiError.
 */
import createClient from 'openapi-fetch'
import type { components, paths } from './schema.gen'

export type Schemas = components['schemas']

/** Ошибка API: HTTP-статус и сообщение бэкенда для пользователя. */
export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/** Сообщение для пользователя из любой ошибки запроса. */
export function errorMessage(error: unknown, fallback = 'Не удалось выполнить запрос'): string {
  if (error instanceof ApiError && error.message) return error.message
  if (error instanceof TypeError) return 'Нет связи с сервером. Проверьте подключение.'
  return fallback
}

function detailOf(body: unknown): string | undefined {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
  }
  return undefined
}

export const api = createClient<paths>({ baseUrl: '' })

/**
 * Результат openapi-fetch -> данные или ApiError. Используется во всех queryFn и mutationFn:
 * `unwrap(await api.GET('/api/v1/projects/{project_id}', …))`.
 */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error !== undefined || !result.response.ok) {
    throw new ApiError(
      result.response.status,
      detailOf(result.error) ?? `Ошибка сервера (${result.response.status})`,
    )
  }
  return result.data as T
}

export interface UploadOptions {
  /** Ход загрузки 0..1. */
  onProgress?: (fraction: number) => void
  signal?: AbortSignal
}

/**
 * POST multipart/form-data через XMLHttpRequest — ради хода загрузки (fetch его не сообщает).
 * Ответ — JSON; при ошибке — ApiError с `detail` бэкенда.
 */
export function postForm<T>(url: string, form: FormData, options: UploadOptions = {}): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', url)
    xhr.responseType = 'json'
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) options.onProgress?.(event.loaded / event.total)
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        options.onProgress?.(1)
        resolve(xhr.response as T)
      } else {
        reject(new ApiError(xhr.status, detailOf(xhr.response) ?? `Ошибка сервера (${xhr.status})`))
      }
    }
    xhr.onerror = () => reject(new TypeError('network'))
    xhr.onabort = () => reject(new DOMException('Загрузка отменена', 'AbortError'))
    options.signal?.addEventListener('abort', () => xhr.abort(), { once: true })
    xhr.send(form)
  })
}

/** Адрес SSE-потока событий прогона. */
export function runEventsUrl(runId: string): string {
  return `/api/v1/runs/${encodeURIComponent(runId)}/events`
}

/** Адрес скачивания XML версии (.bpmn). */
export function versionXmlUrl(versionId: string): string {
  return `/api/v1/versions/${encodeURIComponent(versionId)}/xml`
}
