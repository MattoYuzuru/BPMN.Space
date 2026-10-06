import { parentPort, workerData } from 'node:worker_threads'
import { layout, lint } from './tools.mjs'

try {
  const result = await (workerData.operation === 'layout' ? layout : lint)(workerData.xml)
  parentPort.postMessage({ ok: true, result })
} catch (error) {
  parentPort.postMessage({ ok: false, message: String(error.message).slice(0, 400) })
}
