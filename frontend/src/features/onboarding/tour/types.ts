import type { OnboardingSignal, OnboardingSignalType } from '@/shared/lib/onboarding-signals'
import type { AnchorRef } from '@/shared/lib/tour-anchors'

export type TourSide = 'top' | 'right' | 'bottom' | 'left'
export type TourAlign = 'start' | 'center' | 'end'

/** Где живёт шаг. Движок сам переходит на этот маршрут и ставит тур на паузу, если пользователь ушёл. */
export interface RouteTarget {
  /** Путь маршрута TanStack Router: `/projects`, `/projects/$projectId`. */
  to: string
  params?: Record<string, string>
  search?: Record<string, unknown>
  /** Другие маршруты, на которых шаг тоже считается «на своём экране» (например `/` и `/projects`). */
  alt?: ReadonlyArray<{ to: string; params?: Record<string, string> }>
}

/** Страница шага. Всё, кроме текста, наследуется от шага. */
export interface CoachPage {
  text: string
  /** Свой заголовок страницы (иначе заголовок шага). */
  title?: string
  /** Свой якорь страницы; `null` — по центру экрана без выреза. */
  anchor?: AnchorRef | null
  side?: TourSide
  /** Выравнивание карточки вдоль стороны. */
  align?: TourAlign
  /** Опора карточки: элемент, рядом с которым она стоит, отдельно от выреза (`null` — сам якорь). */
  cardAnchor?: AnchorRef | null
  allowOutside?: boolean
}

/** Последний пойманный сигнал каждого типа за время текущего шага. */
export type SignalMemory = {
  [T in OnboardingSignalType]?: Extract<OnboardingSignal, { type: T }>
}

/** Что можно делать из кнопок шага. */
export interface TourApi {
  /** Следующая страница шага-рассказа или следующий шаг. */
  next: () => void
  /** Предыдущая страница или предыдущий рассказ. */
  back: () => void
  /** Пропустить шаг (следующий видимый шаг). */
  skipStep: () => void
  /** Перейти к шагу по ключу (ветвления: «Пропустить главу», «Повторить»). */
  goto: (key: string) => void
  /** Завершить тур: `completed` или `dismissed`. */
  finish: (reason?: TourEndReason) => void
}

export type TourEndReason = 'completed' | 'dismissed'

export interface StepAction {
  id: string
  label: string
  variant?: 'primary' | 'secondary' | 'ghost'
  tone?: 'default' | 'danger'
  run: (api: TourApi) => void
}

export interface StepViewContext<Ctx> {
  ctx: Ctx
  /** Сколько мс прошло с входа в шаг (обновляется в моменты `ticks`). */
  elapsedMs: number
  /** Сигналы, пойманные с входа в шаг. */
  seen: SignalMemory
  page: number
}

/** Динамические поля шага: перекрывают статические. */
export interface StepView {
  title?: string
  pages?: CoachPage[]
  /** waiting — «ждём» (спиннер у счётчика), error — заголовок тона Сурик. */
  tone?: 'default' | 'waiting' | 'error'
  /** Заменяет кнопки справа (кнопка «Назад» и крестик остаются по правилам движка). */
  actions?: StepAction[]
  /** `null` — по центру экрана без выреза. */
  anchor?: AnchorRef | null
  side?: TourSide
  align?: TourAlign
  cardAnchor?: AnchorRef | null
  allowOutside?: boolean
}

/**
 * Шаг тура — данные, не компоненты. Сценарий — массив таких шагов.
 *
 * - `story` — рассказ: «Далее» / «Назад», «Назад» только у рассказов;
 * - `action` — пользователь делает действие на подсвеченном элементе, шаг идёт дальше по `until`
 *   или `doneWhen`; всегда есть «Пропустить шаг»;
 * - `wait` — ожидание без действий (ход прогона): идёт дальше по `until` / `doneWhen`;
 * - `finish` — финал, по центру; кнопки задаёт шаг (`actions`), по умолчанию «Готово».
 */
export interface TourStep<Ctx = unknown> {
  /** Совпадает с ключом шага на бэкенде. */
  key: string
  /** Ключ главы (подпись берётся из `chapters` у TourHost); `null` — без главы. */
  chapter: string | null
  title: string
  kind: 'action' | 'story' | 'wait' | 'finish'
  /** 1–3 страницы текста. */
  pages: CoachPage[]
  /** Экран шага; нет — шаг не привязан к маршруту (демо, финал). */
  route?: (ctx: Ctx) => RouteTarget | undefined
  /** Якорь `data-tour`; нет — карточка по центру. */
  anchor?: AnchorRef | ((ctx: Ctx) => AnchorRef | undefined)
  side?: TourSide
  align?: TourAlign
  /** Опора карточки (например, вся карточка вопроса при подсвеченной кнопке в ней). */
  cardAnchor?: AnchorRef | ((ctx: Ctx) => AnchorRef | undefined)
  /** Шаг-действие или ожидание завершены этим сигналом. */
  until?: (signal: OnboardingSignal, ctx: Ctx) => boolean
  /** То же по состоянию приложения: проверяется после каждого обновления контекста. */
  doneWhen?: (ctx: Ctx) => boolean
  /** Подготовить экран при входе в шаг (развернуть панель). Может вернуть функцию очистки. */
  prepare?: (ctx: Ctx) => undefined | (() => void)
  /** Шаг пропускается (при входе и пока идёт). Не должен давать true, пока данные ещё грузятся. */
  skipIf?: (ctx: Ctx) => boolean
  /** Если якорь не найден — шаг молча пропускается, а не показывается по центру. */
  optional?: boolean
  /** Клики вне выреза разрешены (шаг «подвигайте схему»). */
  allowOutside?: boolean
  /** Кнопки справа вместо стандартных. */
  actions?: StepAction[]
  /** Динамический вид шага: страницы, тон, кнопки, якорь по контексту и времени. */
  view?: (view: StepViewContext<Ctx>) => StepView | undefined
  /** Моменты (мс от входа в шаг), в которые надо пересчитать `view` (таймаут «60 с», «150 с»). */
  ticks?: readonly number[]
}

export type TourStatus = 'pending' | 'active' | 'completed' | 'dismissed'

/**
 * Хранилище прогресса тура. Движок не знает про API: реальную привязку (`/me/onboarding/tour`)
 * делает сценарий. Вызовы идут «в фоне» с одним повтором при сетевой ошибке.
 */
export interface TourPersistence {
  /** Состояние с сервера: восстановление тура при загрузке любой вкладки. */
  load: () => Promise<{ status: TourStatus; step: string | null }>
  /** Вход в шаг. */
  saveStep: (step: string) => Promise<unknown> | undefined
  /** Начало, завершение, отказ. */
  setStatus: (status: 'active' | 'completed' | 'dismissed') => Promise<unknown> | undefined
}
