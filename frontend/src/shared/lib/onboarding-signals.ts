/**
 * Шина сигналов приложения для обучения. Фичи **публикуют** события о том, что сделал
 * пользователь; тур и чек-лист только слушают. Без подписчиков публикация ничего не делает,
 * зависимостей фич от тура нет. Сигналы публикуются после успеха на сервере.
 */

export type RunSignalStatus = 'queued' | 'running'

/** Действие, которым человек снял технический вопрос прогона (RFC-0006). */
export type TechnicalQuestionAction = 'retry' | 'settings' | 'skip' | 'budget'

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
  /** Технический вопрос к материалам и запуску снят действием пользователя (RFC-0006). */
  | { type: 'question.technical.resolved'; id: string; action: TechnicalQuestionAction }
  | { type: 'share.created' }
  /** Ссылка проверки для коллеги (роль reviewer, RFC-0007, волна 4). */
  | { type: 'share.reviewer.created' }
  | { type: 'dialog.opened'; name: string }
  // Ниже — сигналы волн 2–4. Публикуются после успеха на сервере (копирование команды —
  // клиентский факт после ответа буфера); шаги будущего агентского тура будут их ждать.
  /** Оценка стоимости прогона получена до запуска (RFC-0005). */
  | { type: 'run.estimated'; costMin: number; costMax: number; currency: string; complete: boolean }
  /** Бюджет прогона изменён пользователем (RFC-0005, шаг 5). */
  | { type: 'run.budget.updated'; costUsd: number | null }
  /** Журнал решений прогона открыт: кто, чем и сколько разбирал материалы (RFC-0006). */
  | { type: 'run.decisions.opened'; runId: string }
  /** Ключ под тип задачи добавлен и проверен: распознавание, OCR, vision (RFC-0006, волна 2). */
  | { type: 'tool.credential.added'; kind: string }
  /** Персональный токен для агента создан (RFC-0007). */
  | { type: 'agent.token.created'; id: string; name: string }
  /** Команда подключения агента скопирована (клиентский факт после успешного копирования). */
  | { type: 'agent.command.copied' }
  /** Запись перемотана на таймкод цитаты в плеере (RFC-0006, волна 3). */
  | { type: 'source.player.seek'; sourceId: string; seconds: number }

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
