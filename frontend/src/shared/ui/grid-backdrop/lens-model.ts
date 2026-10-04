/**
 * Чистая модель линзы сетки-подложки: сглаживание следования за курсором, сила линзы,
 * условия включения. Без DOM и WebGL — покрыта тестами отдельно от отрисовки.
 */

/** Радиус зоны линзы, CSS px. */
export const LENS_RADIUS = 180
/** Сжатие выборки в центре (uMagnify): сетка там выглядит крупнее примерно в 1/(1 − 0.18) раза. */
export const LENS_MAGNIFY = 0.18
/** Постоянная времени следования за курсором, мс. Экспоненциальное сглаживание, не пружина. */
export const LENS_POSITION_TAU_MS = 80
/** За это время сила линзы доходит до 99 % цели (выход из окна, вход и уход с карточки). */
export const LENS_FADE_MS = 220
const LENS_STRENGTH_TAU_MS = LENS_FADE_MS / Math.log(100)
/** Ближе этого расстояния линза считается дошедшей до курсора, px. */
export const LENS_POSITION_EPSILON = 0.1
/** Ближе этой разницы сила считается дошедшей до цели. */
export const LENS_STRENGTH_EPSILON = 0.01
/** Длинный кадр (вкладка была скрыта) не должен делать скачок. */
const MAX_FRAME_MS = 100

export interface LensState {
  /** Позиция линзы, CSS px окна. */
  x: number
  y: number
  /** Сила 0..1: 0 — сетка без искажения. */
  strength: number
}

export interface LensTarget {
  x: number
  y: number
  /** Линза нужна: курсор в окне и не над элементом с data-lens-block. */
  active: boolean
}

export const INITIAL_LENS_STATE: LensState = { x: 0, y: 0, strength: 0 }
export const INITIAL_LENS_TARGET: LensTarget = { x: 0, y: 0, active: false }

/** Доля пути к цели за dt: 1 − e^(−dt/τ). Не зависит от частоты кадров. */
export function smoothingFactor(dtMs: number, tauMs: number): number {
  if (dtMs <= 0) return 0
  return 1 - Math.exp(-dtMs / tauMs)
}

/** Один шаг сглаживания: позиция догоняет курсор, сила — цель (0 или 1). Перелёта нет. */
export function stepLens(state: LensState, target: LensTarget, dtMs: number): LensState {
  const dt = Math.min(dtMs, MAX_FRAME_MS)
  const kPos = smoothingFactor(dt, LENS_POSITION_TAU_MS)
  const kStrength = smoothingFactor(dt, LENS_STRENGTH_TAU_MS)
  let x = state.x + (target.x - state.x) * kPos
  let y = state.y + (target.y - state.y) * kPos
  if (Math.hypot(target.x - x, target.y - y) < LENS_POSITION_EPSILON) {
    x = target.x
    y = target.y
  }
  const goal = target.active ? 1 : 0
  let strength = state.strength + (goal - state.strength) * kStrength
  if (Math.abs(goal - strength) < LENS_STRENGTH_EPSILON) strength = goal
  return { x, y, strength }
}

/**
 * Пришло движение курсора. Если линза невидима (сила ≈ 0), она появляется прямо в точке курсора,
 * а не «едет» из старой позиции; иначе позицию догонит сглаживание.
 */
export function placeOnPointer(state: LensState, x: number, y: number): LensState {
  return state.strength <= LENS_STRENGTH_EPSILON ? { x, y, strength: state.strength } : state
}

/** Нужен ли ещё кадр: пока сглаживание не сошлось. Невидимая линза не требует кадров. */
export function lensNeedsFrame(state: LensState, target: LensTarget): boolean {
  const goal = target.active ? 1 : 0
  if (state.strength !== goal) return true
  if (state.strength === 0) return false
  return Math.hypot(target.x - state.x, target.y - state.y) >= LENS_POSITION_EPSILON
}

/** Над этим элементом линза гаснет (карточка формы и всё, что помечено data-lens-block). */
export function isLensBlocked(element: EventTarget | null): boolean {
  return element instanceof Element && element.closest('[data-lens-block]') !== null
}

export interface LensEnvironment {
  reducedMotion: boolean
  /** Есть точный указатель с наведением: мышь, трекпад, перо. */
  finePointerWithHover: boolean
}

/** Линза включается только с мышью и без «сократить движение»; иначе остаётся CSS-сетка. */
export function isLensAllowed(env: LensEnvironment): boolean {
  return !env.reducedMotion && env.finePointerWithHover
}
