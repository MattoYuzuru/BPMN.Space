import { createServer } from 'node:http'
import { pathToFileURL } from 'node:url'
import { PoolError, WorkerPool } from './pool.mjs'

const MAX_BODY = 8 * 1024 * 1024
const MAX_XML = 5 * 1024 * 1024
const timeoutMs = Math.max(100, Number(process.env.BPMN_TOOLS_TIMEOUT_SEC || 20) * 1000)

const envInt = (name, fallback) => {
  const value = Number.parseInt(process.env[name] ?? '', 10)
  return Number.isFinite(value) && value > 0 ? value : fallback
}

export function createToolsServer({
  deadlineMs = timeoutMs,
  poolSize = envInt('BPMN_TOOLS_POOL_SIZE', 2),
  queueLimit = envInt('BPMN_TOOLS_QUEUE_LIMIT', 32),
  maxJobsPerWorker = envInt('BPMN_TOOLS_WORKER_MAX_JOBS', 200),
  workerUrl,
} = {}) {
  const pool = new WorkerPool({
    size: poolSize,
    queueLimit,
    jobTimeoutMs: deadlineMs,
    maxJobsPerWorker,
    ...(workerUrl ? { workerUrl } : {}),
  })
  const server = createServer(async (request, response) => {
    const send = (status, body) => {
      if (!response.destroyed) {
        response.writeHead(status, { 'content-type': 'application/json; charset=utf-8' })
        response.end(JSON.stringify(body))
      }
    }
    if (request.method === 'GET' && request.url === '/health') {
      send(200, { status: 'ok', layout: '2.0.0-alpha.2', lint: '11.14.0' })
      return
    }
    if (request.method !== 'POST' || !['/layout', '/lint'].includes(request.url)) {
      send(404, { detail: 'Не найдено' })
      return
    }
    const chunks = []
    let length = 0
    let body
    try {
      for await (const chunk of request) {
        length += chunk.length
        if (length > MAX_BODY) {
          send(413, { detail: 'Схема превышает лимит сервиса' })
          return
        }
        chunks.push(chunk)
      }
      body = JSON.parse(Buffer.concat(chunks).toString('utf8'))
    } catch {
      send(422, { detail: 'Некорректный запрос к сервису схем' })
      return
    }
    if (typeof body?.xml !== 'string' || Buffer.byteLength(body.xml) > MAX_XML) {
      send(422, { detail: 'Ожидается BPMN XML размером до 5 МБ' })
      return
    }
    const abort = new AbortController()
    response.on('close', () => abort.abort())
    try {
      const message = await pool.run(request.url.slice(1), body.xml, abort.signal)
      send(message.ok ? 200 : 422, message.ok ? message.result : { detail: message.message })
    } catch (error) {
      if (error instanceof PoolError)
        send(error.status, { detail: error.message, code: error.code })
      else send(503, { detail: 'Не удалось выполнить проверку схемы' })
    }
  })
  server.on('close', () => void pool.close())
  server.pool = pool
  return server
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const server = createToolsServer()
  server.requestTimeout = timeoutMs + 5000
  server.listen(3000, '0.0.0.0')
  process.on('SIGTERM', () => server.close())
}
