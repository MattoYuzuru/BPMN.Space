import { parentPort } from 'node:worker_threads'
import { layout, lint } from './tools.mjs'

// Долгоживущий worker: пул шлёт задачи сообщениями {id, operation, xml}, ответ — {id, ok, ...}.
parentPort.on('message', async ({ id, operation, xml }) => {
  try {
    const result = await (operation === 'layout' ? layout : lint)(xml)
    parentPort.postMessage({ id, ok: true, result })
  } catch (error) {
    parentPort.postMessage({ id, ok: false, message: String(error.message).slice(0, 400) })
  }
})
