import { vi } from 'vitest'

export interface StubbedResponse {
  status?: number
  body?: unknown
  headers?: Record<string, string>
}

export interface RecordedRequest {
  method: string
  url: string
  withCredentials: boolean
  headers: Map<string, string>
  body: FormData | undefined
}

/**
 * Подменяет XMLHttpRequest и fetch для проверки загрузок: ответы XHR выдаются по очереди,
 * `/auth/csrf` отдаёт токены `csrf-1`, `csrf-2`… Возвращает журнал запросов.
 */
export function stubUploads(responses: StubbedResponse[]) {
  const requests: RecordedRequest[] = []
  const aborted: boolean[] = []
  let csrfCalls = 0

  class MockXMLHttpRequest {
    responseType = ''
    withCredentials = false
    status = 0
    response: unknown = null
    onload: (() => void) | null = null
    onerror: (() => void) | null = null
    onabort: (() => void) | null = null
    upload = { onprogress: null as ((event: ProgressEvent) => void) | null }
    private request: RecordedRequest = {
      method: '',
      url: '',
      withCredentials: false,
      headers: new Map(),
      body: undefined,
    }
    private reply: StubbedResponse = {}

    open(method: string, url: string) {
      this.request.method = method
      this.request.url = url
    }

    setRequestHeader(name: string, value: string) {
      this.request.headers.set(name, value)
    }

    getResponseHeader(name: string) {
      return this.reply.headers?.[name] ?? null
    }

    abort() {
      aborted.push(true)
      this.onabort?.()
    }

    send(body: FormData) {
      this.request.body = body
      this.request.withCredentials = this.withCredentials
      requests.push(this.request)
      this.reply = responses[requests.length - 1] ?? { status: 200, body: {} }
      this.status = this.reply.status ?? 200
      this.response = this.reply.body ?? {}
      queueMicrotask(() => this.onload?.())
    }
  }

  vi.stubGlobal('XMLHttpRequest', MockXMLHttpRequest)
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      csrfCalls += 1
      return new Response(JSON.stringify({ csrf_token: `csrf-${csrfCalls}` }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
  return { requests, aborted, csrfCalls: () => csrfCalls }
}
