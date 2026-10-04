/**
 * Типизированный клиент API v1 (openapi-fetch по schema.gen.ts) и вспомогательные запросы,
 * которые openapi-fetch не покрывает: multipart с ходом загрузки и адрес SSE-потока.
 * Ошибки бэкенда — `{"detail": "…"}` на русском; наружу выходят как ApiError.
 */
import createClient from 'openapi-fetch'
import type { components, paths } from './schema.gen'

export type Schemas = components['schemas']

const API_PREFIX = '/api/v1/'
const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])
let csrfTokenPromise: Promise<string> | undefined

/** Ошибка API: HTTP-статус и сообщение бэкенда для пользователя. */
export class ApiError extends Error {
  readonly status: number
  /** Машинный код ошибки (`LOGIN_BAD_CREDENTIALS`) — для сопоставления с текстом на экране. */
  readonly code?: string
  /** Через сколько секунд повторить (заголовок Retry-After при 429). */
  readonly retryAfter?: number
  /** Сырое тело `detail`: у ошибок проверки полей это массив с путями полей. */
  readonly detail?: unknown

  constructor(
    status: number,
    message: string,
    extra: { code?: string; retryAfter?: number; detail?: unknown } = {},
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = extra.code
    this.retryAfter = extra.retryAfter
    this.detail = extra.detail
  }
}

/** Сообщение для пользователя из любой ошибки запроса. */
export function errorMessage(error: unknown, fallback = 'Не удалось выполнить запрос'): string {
  if (error instanceof ApiError && error.status === 429) return RATE_LIMIT_MESSAGE
  if (error instanceof ApiError && error.message) return error.message
  if (error instanceof TypeError) return 'Нет связи с сервером. Проверьте подключение.'
  return fallback
}

/** Текст при ограничении частоты запросов (429): спокойно и без цифр, которых пользователь не ждёт. */
export const RATE_LIMIT_MESSAGE = 'Слишком много попыток. Подождите немного и повторите.'

function detailOf(body: unknown): string | undefined {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail
    // Коды fastapi-users (`LOGIN_BAD_CREDENTIALS`) наружу как текст не годятся — их разбирает code.
    if (typeof detail === 'string' && !isErrorCode(detail)) return detail
  }
  return undefined
}

const isErrorCode = (value: string) => /^[A-Z][A-Z0-9_]+$/.test(value)

/** Машинный код из `detail`: строка `LOGIN_BAD_CREDENTIALS` или объект `{code: …}`. */
function codeOf(body: unknown): string | undefined {
  if (!body || typeof body !== 'object' || !('detail' in body)) return undefined
  const detail = (body as { detail: unknown }).detail
  if (typeof detail === 'string') return isErrorCode(detail) ? detail : undefined
  if (detail && typeof detail === 'object' && 'code' in detail) {
    const code = (detail as { code: unknown }).code
    return typeof code === 'string' ? code : undefined
  }
  return undefined
}

function retryAfterOf(header: string | null): number | undefined {
  const seconds = Number(header)
  return Number.isFinite(seconds) && seconds > 0 ? seconds : undefined
}

/** Ошибка из ответа: статус, текст, код и пауза до повтора. */
function apiErrorFrom(response: Response, body: unknown): ApiError {
  return new ApiError(response.status, detailOf(body) ?? `Ошибка сервера (${response.status})`, {
    code: codeOf(body),
    retryAfter: retryAfterOf(response.headers.get('Retry-After')),
    detail: body && typeof body === 'object' && 'detail' in body ? body.detail : undefined,
  })
}

/** Забыть кэшированный CSRF-токен (после смены сессии и в тестах). */
export function resetCsrfToken() {
  csrfTokenPromise = undefined
}

/** Cookie-сессия: перед изменяющим запросом получить CSRF-токен с того же origin. */
export async function getCsrfToken(force = false): Promise<string> {
  if (force) csrfTokenPromise = undefined
  csrfTokenPromise ??= (async () => {
    const response = await globalThis.fetch(`${API_PREFIX}auth/csrf`, {
      credentials: 'same-origin',
    })
    if (!response.ok)
      throw new ApiError(response.status, 'Не удалось подготовить защищённый запрос')
    const payload = (await response.json()) as { csrf_token?: unknown }
    if (typeof payload.csrf_token !== 'string' || !payload.csrf_token) {
      throw new ApiError(response.status, 'Сервер не вернул CSRF-токен')
    }
    return payload.csrf_token
  })().catch((error: unknown) => {
    csrfTokenPromise = undefined
    throw error
  })
  return csrfTokenPromise
}

function withCsrf(request: Request, token: string): Request {
  const headers = new Headers(request.headers)
  headers.set('X-CSRF-Token', token)
  return new Request(request.clone(), { headers, credentials: 'same-origin' })
}

async function fetchWithCsrf(request: Request): Promise<Response> {
  const isApi = new URL(request.url).pathname.startsWith(API_PREFIX)
  const unsafe = UNSAFE_METHODS.has(request.method.toUpperCase())
  if (!isApi || !unsafe) return globalThis.fetch(request)

  const template = request.clone()
  const token = await getCsrfToken()
  const response = await globalThis.fetch(withCsrf(template.clone(), token))
  if (response.status !== 403) return response

  const body = (await response
    .clone()
    .json()
    .catch(() => null)) as { detail?: unknown } | null
  if (typeof body?.detail !== 'string' || !body.detail.toLowerCase().includes('csrf')) {
    return response
  }
  const renewedToken = await getCsrfToken(true)
  return globalThis.fetch(withCsrf(template.clone(), renewedToken))
}

/** Адрес от текущего origin; fetch берётся в момент запроса, чтобы его можно было подменить в тестах. */
export const api = createClient<paths>({
  baseUrl: globalThis.location?.origin ?? '',
  fetch: fetchWithCsrf,
})

/**
 * Результат openapi-fetch -> данные или ApiError. Используется во всех queryFn и mutationFn:
 * `unwrap(await api.GET('/api/v1/projects/{project_id}', …))`.
 */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error !== undefined || !result.response.ok) {
    throw apiErrorFrom(result.response, result.error)
  }
  return result.data as T
}

export interface UploadOptions {
  /** Ход загрузки 0..1. */
  onProgress?: (fraction: number) => void
  signal?: AbortSignal
}

/** Один XHR-запрос multipart с заданным CSRF-токеном. */
function sendForm<T>(
  url: string,
  form: FormData,
  csrfToken: string,
  options: UploadOptions,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', url)
    xhr.withCredentials = true
    xhr.setRequestHeader('X-CSRF-Token', csrfToken)
    xhr.responseType = 'json'
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) options.onProgress?.(event.loaded / event.total)
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        options.onProgress?.(1)
        resolve(xhr.response as T)
      } else {
        reject(
          new ApiError(xhr.status, detailOf(xhr.response) ?? `Ошибка сервера (${xhr.status})`, {
            code: codeOf(xhr.response),
            retryAfter: retryAfterOf(xhr.getResponseHeader('Retry-After')),
          }),
        )
      }
    }
    xhr.onerror = () => reject(new TypeError('network'))
    xhr.onabort = () => reject(new DOMException('Загрузка отменена', 'AbortError'))
    options.signal?.addEventListener('abort', () => xhr.abort(), { once: true })
    xhr.send(form)
  })
}

const abortedError = () => new DOMException('Загрузка отменена', 'AbortError')

/** 403 из-за просроченного CSRF-токена (а не из-за прав доступа). */
function isCsrfRejection(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.status === 403 &&
    error.message.toLowerCase().includes('csrf')
  )
}

/**
 * POST multipart/form-data через XMLHttpRequest — ради хода загрузки (fetch его не сообщает).
 * Ответ — JSON; при ошибке — ApiError с `detail` бэкенда. Как и fetchWithCsrf, один раз
 * повторяет запрос с новым токеном, если прежний отклонён; уже отменённый signal не стартует.
 */
export async function postForm<T>(
  url: string,
  form: FormData,
  options: UploadOptions = {},
): Promise<T> {
  if (options.signal?.aborted) throw abortedError()
  try {
    return await sendForm<T>(url, form, await getCsrfToken(), options)
  } catch (error) {
    if (!isCsrfRejection(error) || options.signal?.aborted) throw error
    return sendForm<T>(url, form, await getCsrfToken(true), options)
  }
}

/** Адрес SSE-потока событий прогона. */
export function runEventsUrl(runId: string): string {
  return `/api/v1/runs/${encodeURIComponent(runId)}/events`
}

/** Адрес скачивания XML версии (.bpmn). */
export function versionXmlUrl(versionId: string): string {
  return `/api/v1/versions/${encodeURIComponent(versionId)}/xml`
}
