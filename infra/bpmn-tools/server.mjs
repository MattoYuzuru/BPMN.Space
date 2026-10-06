import { createServer } from 'node:http'
import { pathToFileURL } from 'node:url'
import { Worker } from 'node:worker_threads'

const MAX_BODY = 8 * 1024 * 1024
const MAX_XML = 5 * 1024 * 1024
const timeoutMs = Math.max(100, Number(process.env.BPMN_TOOLS_TIMEOUT_SEC || 20) * 1000)

export function createToolsServer({ deadlineMs = timeoutMs } = {}) {
  let active = 0
  return createServer(async (request, response) => {
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
    if (active >= 2) {
      send(503, { detail: 'Сервис проверки схем занят, повторите позже' })
      return
    }
    const chunks = []
    let length = 0
    try {
      for await (const chunk of request) {
        length += chunk.length
        if (length > MAX_BODY) {
          send(413, { detail: 'Схема превышает лимит сервиса' })
          return
        }
        chunks.push(chunk)
      }
      const body = JSON.parse(Buffer.concat(chunks).toString('utf8'))
      if (typeof body.xml !== 'string' || Buffer.byteLength(body.xml) > MAX_XML) {
        send(422, { detail: 'Ожидается BPMN XML размером до 5 МБ' })
        return
      }
      if (active >= 2) {
        send(503, { detail: 'Сервис проверки схем занят, повторите позже' })
        return
      }
      const worker = new Worker(new URL('./worker.mjs', import.meta.url), {
        execArgv: [],
        workerData: { operation: request.url.slice(1), xml: body.xml },
        resourceLimits: { maxOldGenerationSizeMb: 256 },
      })
      active += 1
      let ended = false
      const finish = (status, data) => {
        if (ended) return
        ended = true
        active -= 1
        clearTimeout(timer)
        void worker.terminate()
        send(status, data)
      }
      const timer = setTimeout(
        () => finish(504, { detail: 'Проверка или раскладка схемы превысила срок' }),
        deadlineMs,
      )
      response.on('close', () => finish(499, { detail: 'Запрос отменён' }))
      worker.once('message', (result) =>
        finish(result.ok ? 200 : 422, result.ok ? result.result : { detail: result.message }),
      )
      worker.once('error', () => finish(503, { detail: 'Не удалось выполнить проверку схемы' }))
      worker.once('exit', (code) => {
        if (code !== 0 && !ended) finish(503, { detail: 'Проверка схемы прервана' })
      })
    } catch {
      send(422, { detail: 'Некорректный запрос к сервису схем' })
    }
  })
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const server = createToolsServer()
  server.requestTimeout = timeoutMs + 5000
  server.listen(3000, '0.0.0.0')
  process.on('SIGTERM', () => server.close())
}
