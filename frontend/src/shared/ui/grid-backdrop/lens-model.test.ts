import { describe, expect, it } from 'vitest'
import {
  INITIAL_LENS_STATE,
  isLensAllowed,
  isLensBlocked,
  LENS_FADE_MS,
  type LensState,
  type LensTarget,
  lensNeedsFrame,
  placeOnPointer,
  smoothingFactor,
  stepLens,
} from './lens-model'

const FRAME = 1000 / 60

function run(state: LensState, target: LensTarget, frames: number, dt = FRAME) {
  const trace = [state]
  let current = state
  for (let i = 0; i < frames; i++) {
    current = stepLens(current, target, dt)
    trace.push(current)
  }
  return trace
}

describe('smoothingFactor', () => {
  it('равен 1 − e^(−dt/τ) и не зависит от разбиения времени на кадры', () => {
    expect(smoothingFactor(80, 80)).toBeCloseTo(1 - Math.exp(-1), 10)
    const whole = 1 - smoothingFactor(100, 80)
    const halves = (1 - smoothingFactor(50, 80)) ** 2
    expect(halves).toBeCloseTo(whole, 10)
  })

  it('при нулевом dt не двигает', () => {
    expect(smoothingFactor(0, 80)).toBe(0)
  })
})

describe('stepLens: позиция', () => {
  const target: LensTarget = { x: 400, y: 300, active: true }
  const start: LensState = { x: 100, y: 100, strength: 1 }

  it('монотонно приближается к цели без перелёта и колебаний', () => {
    const trace = run(start, target, 200)
    for (let i = 1; i < trace.length; i++) {
      const prev = trace[i - 1] as LensState
      const next = trace[i] as LensState
      expect(next.x).toBeGreaterThanOrEqual(prev.x)
      expect(next.y).toBeGreaterThanOrEqual(prev.y)
      expect(next.x).toBeLessThanOrEqual(target.x)
      expect(next.y).toBeLessThanOrEqual(target.y)
    }
  })

  it('сходится за конечное число кадров и после этого кадры не нужны', () => {
    const trace = run(start, target, 400)
    const settledAt = trace.findIndex((s) => !lensNeedsFrame(s, target))
    expect(settledAt).toBeGreaterThan(0)
    expect(settledAt).toBeLessThan(120)
    expect(trace[settledAt]).toEqual({ x: 400, y: 300, strength: 1 })
  })

  it('за τ проходит около 63 % пути', () => {
    const next = stepLens(start, target, 80)
    expect((next.x - start.x) / (target.x - start.x)).toBeCloseTo(1 - Math.exp(-1), 6)
  })

  it('длинный кадр не делает скачка дальше, чем 100 мс сглаживания', () => {
    const jump = stepLens(start, target, 5000)
    const capped = stepLens(start, target, 100)
    expect(jump).toEqual(capped)
  })
})

describe('stepLens: сила', () => {
  it('падает до нуля за LENS_FADE_MS, когда курсор ушёл', () => {
    const away: LensTarget = { x: 50, y: 50, active: false }
    const frames = Math.ceil(LENS_FADE_MS / FRAME) + 1
    const trace = run({ x: 50, y: 50, strength: 1 }, away, frames)
    for (let i = 1; i < trace.length; i++) {
      expect((trace[i] as LensState).strength).toBeLessThanOrEqual(
        (trace[i - 1] as LensState).strength,
      )
    }
    expect((trace.at(-1) as LensState).strength).toBeLessThan(0.011)
    expect(run({ x: 50, y: 50, strength: 1 }, away, 60).at(-1)?.strength).toBe(0)
  })

  it('растёт к 1, когда курсор в окне и не над карточкой', () => {
    const trace = run({ x: 50, y: 50, strength: 0 }, { x: 50, y: 50, active: true }, 60)
    expect(trace.at(-1)?.strength).toBe(1)
    for (let i = 1; i < trace.length; i++) {
      expect((trace[i] as LensState).strength).toBeGreaterThanOrEqual(
        (trace[i - 1] as LensState).strength,
      )
    }
  })
})

describe('lensNeedsFrame', () => {
  it('невидимая линза с погашенной целью не требует кадров, даже если позиция далеко', () => {
    expect(lensNeedsFrame({ x: 0, y: 0, strength: 0 }, { x: 500, y: 500, active: false })).toBe(
      false,
    )
  })

  it('покой на месте — ноль кадров', () => {
    expect(lensNeedsFrame({ x: 10, y: 10, strength: 1 }, { x: 10, y: 10, active: true })).toBe(
      false,
    )
  })

  it('курсор сдвинулся или сила ещё меняется — кадры нужны', () => {
    expect(lensNeedsFrame({ x: 10, y: 10, strength: 1 }, { x: 40, y: 10, active: true })).toBe(true)
    expect(lensNeedsFrame({ x: 10, y: 10, strength: 0.5 }, { x: 10, y: 10, active: false })).toBe(
      true,
    )
  })
})

describe('placeOnPointer', () => {
  it('невидимая линза появляется в точке входа без прыжка из старой позиции', () => {
    const placed = placeOnPointer({ x: 900, y: 40, strength: 0 }, 120, 80)
    expect(placed).toEqual({ x: 120, y: 80, strength: 0 })
  })

  it('видимая линза позицию не телепортирует — её догоняет сглаживание', () => {
    const state = { x: 900, y: 40, strength: 0.6 }
    expect(placeOnPointer(state, 120, 80)).toBe(state)
  })

  it('начальное состояние невидимо', () => {
    expect(INITIAL_LENS_STATE.strength).toBe(0)
  })
})

describe('isLensBlocked', () => {
  it('гасит линзу над элементом с data-lens-block и над его потомками', () => {
    const card = document.createElement('div')
    card.setAttribute('data-lens-block', '')
    const input = document.createElement('input')
    card.append(input)
    document.body.append(card)
    expect(isLensBlocked(card)).toBe(true)
    expect(isLensBlocked(input)).toBe(true)
    card.remove()
  })

  it('не гасит над обычными элементами и без цели', () => {
    expect(isLensBlocked(document.createElement('div'))).toBe(false)
    expect(isLensBlocked(null)).toBe(false)
    expect(isLensBlocked(window)).toBe(false)
  })
})

describe('isLensAllowed', () => {
  it('включается только с мышью и без «сократить движение»', () => {
    expect(isLensAllowed({ reducedMotion: false, finePointerWithHover: true })).toBe(true)
    expect(isLensAllowed({ reducedMotion: true, finePointerWithHover: true })).toBe(false)
    expect(isLensAllowed({ reducedMotion: false, finePointerWithHover: false })).toBe(false)
  })
})
