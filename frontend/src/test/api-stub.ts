import { vi } from 'vitest'

export interface StubReply {
  status?: number
  body?: unknown
  /** Ответ не JSON, а текст (например, XML). */
  text?: string
}

export interface ApiCall {
  method: string
  path: string
  search: URLSearchParams
  body: unknown
}

type Handler = StubReply | ((call: ApiCall) => StubReply)

/**
 * Подмена fetch для проверки запросов к API. Ключ — «МЕТОД путь» (без origin и query):
 * `'GET /api/v1/shares/tok'`. Неизвестный путь отвечает 404, CSRF-токен выдаётся сам.
 * Возвращает журнал вызовов — по нему тест видит, что и куда было отправлено.
 */
export function stubApi(handlers: Record<string, Handler>) {
  const calls: ApiCall[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : undefined
      const url = new URL(request ? request.url : String(input), 'http://localhost')
      const method = (request?.method ?? init?.method ?? 'GET').toUpperCase()
      if (url.pathname.endsWith('/auth/csrf')) return json(200, { csrf_token: 'csrf-test-token' })
      const raw = request ? await request.clone().text() : String(init?.body ?? '')
      const call: ApiCall = {
        method,
        path: url.pathname,
        search: url.searchParams,
        body: raw ? JSON.parse(raw) : undefined,
      }
      calls.push(call)
      const handler = handlers[`${method} ${url.pathname}`]
      if (!handler) return json(404, { detail: 'Не найдено' })
      const reply = typeof handler === 'function' ? handler(call) : handler
      if (reply.text !== undefined) {
        return new Response(reply.text, {
          status: reply.status ?? 200,
          headers: { 'Content-Type': 'application/xml' },
        })
      }
      return json(reply.status ?? 200, reply.body)
    }),
  )
  return calls
}

function json(status: number, body: unknown) {
  if (status === 204) return new Response(null, { status })
  return new Response(JSON.stringify(body ?? null), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}
