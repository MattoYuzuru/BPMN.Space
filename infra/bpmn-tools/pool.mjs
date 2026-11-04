import { Worker } from 'node:worker_threads'

const DEFAULT_WORKER = new URL('./worker.mjs', import.meta.url)

/** Ошибка пула с готовым HTTP-статусом: busy 503, timeout 504, cancelled 499, crash 503. */
export class PoolError extends Error {
  constructor(code, status, message) {
    super(message)
    this.code = code
    this.status = status
  }
}

/**
 * Тёплый пул worker threads с ограниченной очередью.
 * Worker не создаётся на каждый запрос: библиотеки layout/lint загружаются один раз.
 * Worker пересоздаётся после `maxJobsPerWorker` задач, а также после сбоя, таймаута и отмены
 * (прерванная задача может оставить его в неопределённом состоянии).
 */
export class WorkerPool {
  constructor({
    size = 2,
    queueLimit = 32,
    jobTimeoutMs = 20_000,
    maxJobsPerWorker = 200,
    workerUrl = DEFAULT_WORKER,
    maxOldGenerationSizeMb = 256,
  } = {}) {
    this.size = Math.max(1, size)
    this.queueLimit = Math.max(0, queueLimit)
    this.jobTimeoutMs = jobTimeoutMs
    this.maxJobsPerWorker = Math.max(1, maxJobsPerWorker)
    this.workerUrl = workerUrl
    this.limits = { maxOldGenerationSizeMb }
    this.slots = Array.from({ length: this.size }, () => ({ worker: null, job: null, jobs: 0 }))
    this.queue = []
    this.nextId = 1
    this.closed = false
    this.spawned = 0 // для тестов и диагностики: сколько worker-ов создано за жизнь пула
  }

  get busy() {
    return this.slots.filter((slot) => slot.job).length
  }

  run(operation, xml, signal) {
    if (this.closed) return Promise.reject(new PoolError('closed', 503, 'Сервис останавливается'))
    const idle = this.slots.some((slot) => !slot.job)
    if (!idle && this.queue.length >= this.queueLimit) {
      return Promise.reject(
        new PoolError('busy', 503, 'Сервис проверки схем занят, повторите позже'),
      )
    }
    return new Promise((resolve, reject) => {
      const job = { id: this.nextId++, operation, xml, resolve, reject, signal, timer: null }
      if (signal) {
        if (signal.aborted) {
          reject(new PoolError('cancelled', 499, 'Запрос отменён'))
          return
        }
        job.onAbort = () => this.#cancel(job)
        signal.addEventListener('abort', job.onAbort, { once: true })
      }
      this.queue.push(job)
      this.#dispatch()
    })
  }

  async close() {
    this.closed = true
    for (const job of this.queue.splice(0)) this.#settle(job, 'reject', closedError())
    await Promise.all(
      this.slots.map(async (slot) => {
        if (slot.job) this.#settle(slot.job, 'reject', closedError())
        slot.job = null
        await this.#discard(slot)
      }),
    )
  }

  #dispatch() {
    while (this.queue.length) {
      const slot = this.slots.find((candidate) => !candidate.job)
      if (!slot) return
      const job = this.queue.shift()
      this.#start(slot, job)
    }
  }

  #start(slot, job) {
    if (!slot.worker) this.#spawn(slot)
    slot.job = job
    slot.jobs += 1
    job.timer = setTimeout(
      () =>
        this.#fail(
          slot,
          job,
          new PoolError('timeout', 504, 'Проверка или раскладка схемы превысила срок'),
        ),
      this.jobTimeoutMs,
    )
    slot.worker.postMessage({ id: job.id, operation: job.operation, xml: job.xml })
  }

  #spawn(slot) {
    const worker = new Worker(this.workerUrl, { execArgv: [], resourceLimits: this.limits })
    worker.unref()
    this.spawned += 1
    slot.worker = worker
    slot.jobs = 0
    worker.on('message', (message) => {
      if (slot.worker !== worker || !slot.job || slot.job.id !== message.id) return
      const job = slot.job
      slot.job = null
      this.#settle(job, 'resolve', message)
      if (slot.jobs >= this.maxJobsPerWorker) void this.#discard(slot)
      this.#dispatch()
    })
    const crashed = () => {
      if (slot.worker !== worker) return
      slot.worker = null
      const job = slot.job
      slot.job = null
      if (job) this.#settle(job, 'reject', new PoolError('crash', 503, 'Проверка схемы прервана'))
      this.#dispatch()
    }
    worker.once('error', crashed)
    worker.once('exit', crashed)
  }

  #cancel(job) {
    const queued = this.queue.indexOf(job)
    if (queued >= 0) {
      this.queue.splice(queued, 1)
      this.#settle(job, 'reject', new PoolError('cancelled', 499, 'Запрос отменён'))
      return
    }
    const slot = this.slots.find((candidate) => candidate.job === job)
    if (slot) this.#fail(slot, job, new PoolError('cancelled', 499, 'Запрос отменён'))
  }

  #fail(slot, job, error) {
    if (slot.job !== job) return
    slot.job = null
    this.#settle(job, 'reject', error)
    void this.#discard(slot).then(() => this.#dispatch())
  }

  async #discard(slot) {
    const worker = slot.worker
    slot.worker = null
    slot.jobs = 0
    if (worker) await worker.terminate().catch(() => {})
  }

  #settle(job, how, value) {
    clearTimeout(job.timer)
    if (job.signal && job.onAbort) job.signal.removeEventListener('abort', job.onAbort)
    job[how](value)
  }
}

function closedError() {
  return new PoolError('closed', 503, 'Сервис останавливается')
}
