import { parentPort } from 'node:worker_threads'

// Тестовый worker: на 'crash' аварийно завершается, иначе отвечает успехом.
parentPort.on('message', ({ id, xml }) => {
  if (xml === 'crash') process.exit(3)
  parentPort.postMessage({ id, ok: true, result: { xml } })
})
