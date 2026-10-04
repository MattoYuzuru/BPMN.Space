const RETRY_DELAY_MS = 1500

/**
 * Фоновая запись на сервер: не ждём ответа, при ошибке один повтор через паузу.
 * Прогресс обучения не должен тормозить интерфейс или ломать его при сбое сети.
 */
export function persistQuietly(task: () => Promise<unknown> | undefined): void {
  const run = async () => {
    await task()
  }
  run().catch(() => {
    window.setTimeout(() => {
      run().catch(() => {})
    }, RETRY_DELAY_MS)
  })
}
