/**
 * Шина сигналов приложения для обучения. Фичи **публикуют** события о том, что сделал
 * пользователь; тур и чек-лист только слушают. Без подписчиков публикация ничего не делает,
 * зависимостей фич от тура нет. Сигналы публикуются после успеха на сервере.
 */

export type RunSignalStatus = 'queued' | 'running'

export type OnboardingSignal =
  | { type: 'project.created'; id: string }
  | { type: 'source.added'; kind: string }
  | { type: 'voice.permission-denied' }
  | { type: 'voice.unavailable' }
  /** Прогон реально запущен пользователем (не повторное подключение к идущему). */
  | { type: 'run.started'; id: string; projectId: string }
  | { type: 'run.status'; status: RunSignalStatus; projectId: string }
  /** Итог прогона показан; бизнес-сигнал run.finished приходит независимо и раньше. */
  | { type: 'run.presented'; runId: string; projectId: string }
  | {
      type: 'run.finished'
      status: string
      openQuestions: number
      hasDiagram: boolean
      projectId: string
    }
  | { type: 'question.answered'; id: string }
  | { type: 'question.ignored'; id: string }
  | { type: 'share.created' }
  | { type: 'dialog.opened'; name: string }

export type OnboardingSignalType = OnboardingSignal['type']

export type OnboardingSignalListener = (signal: OnboardingSignal) => void

const listeners = new Set<OnboardingSignalListener>()

/** Опубликовать сигнал. Дёшево: без подписчиков — пустая проверка. */
export function emitOnboardingSignal(signal: OnboardingSignal): void {
  if (listeners.size === 0) return
  for (const listener of [...listeners]) listener(signal)
}

/** Подписаться на сигналы; возвращает функцию отписки. */
export function subscribeOnboardingSignals(listener: OnboardingSignalListener): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** Есть ли подписчики (для тестов и диагностики). */
export function hasOnboardingSubscribers(): boolean {
  return listeners.size > 0
}
