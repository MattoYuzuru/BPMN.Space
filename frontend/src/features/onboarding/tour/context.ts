import type { RunResult } from './session'

/** Панели рабочего места, которые тур разворачивает. */
export type TourPanel = 'sources' | 'questions'

/**
 * Рычаги экрана. Тур не знает про виджеты и фичи: сборка (`TourRoot`) подставляет сюда публичные
 * точки расширения — `useWorkspaceUi`, `useCreateProjectDialog`, `useOnboardingUi`.
 */
export interface TourUi {
  expandPanel: (panel: TourPanel) => void
  /** Показать во вкладке «Открытые» панели «Вопросы». */
  showOpenQuestions: () => void
  /** Подсказка-автодополнение для диалога текстового источника; `null` — убрать. */
  setTextSuggestion: (text: string | null) => void
  /**
   * Подменить параметры открытия «Нового проекта» по клику пользователя: пустой режим, название от
   * `title()`, без описания и документов. `null` — вернуть как было.
   */
  interceptCreate: (title: (() => string) | null) => void
  /** Закрыть диалоги источников рабочего места. */
  closeDialogs: () => void
  /** Закрыть верхнее открытое окно (после создания ссылки доступа). */
  closeTopDialog: () => void
  openChecklist: () => void
}

/** Какие якоря сейчас на экране: по ним шаги выбирают, куда смотреть (кнопка меню или поле окна). */
export interface TourPresence {
  createSubmit: boolean
  textContent: boolean
  voiceCapture: boolean
  shareCreate: boolean
  shareCopy: boolean
}

/** Действия, которые не сводятся к переходу между шагами. */
export interface TourOperations {
  /** «Начать заново»: новый тур с первого шага без учебного проекта. */
  restart: () => Promise<void>
  /** «Повторить»: новый прогон сборки. */
  retryRun: () => void
}

/**
 * Данные для шагов. Поля, которые меняются сигналом и должны быть свежими уже в момент перехода
 * (проект, итог прогона, ответ, ссылка), — геттеры, читающие сессию тура напрямую.
 */
export interface TourContext {
  /** Учебный проект. */
  readonly projectId: string | null
  /** Данные учебного проекта получены. До этого шаги ничего не пропускают. */
  loaded: boolean
  /** Проект удалён во время тура. */
  deleted: boolean
  /** Название для нового учебного проекта. */
  readonly firstTitle: string
  sources: number
  /** Источников в разборе (документы .docx и .pdf). */
  processing: number
  runActive: boolean
  /** Прогон ждёт своей очереди. */
  readonly queued: boolean
  /** Этап прогона по событиям потока. */
  stage: string | null
  readonly result: RunResult | null
  /** Открытые вопросы в порядке панели. */
  openQuestionIds: string[]
  /** Вопрос шага 7: ответивший на него — до ответа и после. */
  readonly pickedId: string | null
  readonly shareCreated: boolean
  present: TourPresence
  /** Подсказка для шага 3 от сервера. */
  textSuggestion: string | null
  ui: TourUi
  ops: TourOperations
}
