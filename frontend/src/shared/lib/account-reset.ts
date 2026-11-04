/**
 * Сброс состояния, привязанного к аккаунту, вне кэша запросов: хранилища zustand регистрируют
 * себя здесь, а выход, вход и истёкшая сессия вызывают `resetAccountState`, не зная о хранилищах.
 */
const resets = new Set<() => void>()

/** Регистрирует функцию сброса; возвращает отписку (нужна тестам). */
export function registerAccountReset(reset: () => void): () => void {
  resets.add(reset)
  return () => {
    resets.delete(reset)
  }
}

export function resetAccountState() {
  for (const reset of [...resets]) reset()
}
