/**
 * Геометрия видимой области (viewbox) и плавные переходы между ними.
 * Чистые функции — без bpmn-js, чтобы тестировать без настоящего canvas.
 */

export interface Box {
  x: number
  y: number
  width: number
  height: number
}

export interface Size {
  width: number
  height: number
}

export const MIN_SCALE = 0.2
export const MAX_SCALE = 4
/** Ниже этого масштаба подписи не читаются: focusElement приближает. */
const READABLE_SCALE = 0.75

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

export function scaleOf(outer: Size, viewbox: Box): number {
  return outer.width / viewbox.width
}

/** Viewbox с центром в точке и заданным масштабом. */
function around(outer: Size, cx: number, cy: number, scale: number): Box {
  const width = outer.width / scale
  const height = outer.height / scale
  return { x: cx - width / 2, y: cy - height / 2, width, height }
}

/** Масштаб, при котором bbox с отступами целиком помещается в окно. */
function fitScale(outer: Size, bbox: Box, padding: number): number {
  const width = Math.max(outer.width - padding * 2, 1)
  const height = Math.max(outer.height - padding * 2, 1)
  return Math.min(width / Math.max(bbox.width, 1), height / Math.max(bbox.height, 1))
}

/** Вписать bbox в окно с отступами, не увеличивая больше `maxScale` (по умолчанию 100 %). */
export function fitViewbox(outer: Size, bbox: Box, padding = 48, maxScale = 1): Box {
  const scale = clamp(fitScale(outer, bbox, padding), MIN_SCALE, maxScale)
  return around(outer, bbox.x + bbox.width / 2, bbox.y + bbox.height / 2, scale)
}

/**
 * Центрировать bbox, по возможности сохранив масштаб.
 * Если элемент не помещается — отдаляем; если масштаб слишком мелкий для чтения — приближаем до 100 %.
 */
export function focusViewbox(outer: Size, current: Box, bbox: Box, padding = 96): Box {
  const currentScale = scaleOf(outer, current)
  const fit = fitScale(outer, bbox, padding)
  let scale = currentScale
  if (scale > fit) scale = fit
  else if (scale < READABLE_SCALE) scale = Math.min(1, fit)
  return around(
    outer,
    bbox.x + bbox.width / 2,
    bbox.y + bbox.height / 2,
    clamp(scale, MIN_SCALE, MAX_SCALE),
  )
}

/** Шаг масштаба вокруг центра окна. */
export function zoomViewbox(outer: Size, current: Box, factor: number): Box {
  const scale = clamp(scaleOf(outer, current) * factor, MIN_SCALE, MAX_SCALE)
  return around(outer, current.x + current.width / 2, current.y + current.height / 2, scale)
}

/** Объединённый bbox нескольких прямоугольников. */
export function unionBox(boxes: readonly Box[]): Box | null {
  if (boxes.length === 0) return null
  let minX = Number.POSITIVE_INFINITY
  let minY = Number.POSITIVE_INFINITY
  let maxX = Number.NEGATIVE_INFINITY
  let maxY = Number.NEGATIVE_INFINITY
  for (const box of boxes) {
    minX = Math.min(minX, box.x)
    minY = Math.min(minY, box.y)
    maxX = Math.max(maxX, box.x + box.width)
    maxY = Math.max(maxY, box.y + box.height)
  }
  return { x: minX, y: minY, width: maxX - minX, height: maxY - minY }
}

/**
 * Промежуточный viewbox. Интерполируем центр и логарифм масштаба:
 * так приближение воспринимается равномерным, без рывка в конце.
 */
export function interpolateViewbox(from: Box, to: Box, t: number): Box {
  const lerp = (a: number, b: number) => a + (b - a) * t
  const width = Math.exp(lerp(Math.log(from.width), Math.log(to.width)))
  const height = width * (from.height / from.width)
  const cx = lerp(from.x + from.width / 2, to.x + to.width / 2)
  const cy = lerp(from.y + from.height / 2, to.y + to.height / 2)
  return { x: cx - width / 2, y: cy - height / 2, width, height }
}

/** CSS cubic-bezier(x1, y1, x2, y2) как функция времени: Ньютон с запасным делением пополам. */
export function cubicBezier(x1: number, y1: number, x2: number, y2: number): (t: number) => number {
  const cx = 3 * x1
  const bx = 3 * (x2 - x1) - cx
  const ax = 1 - cx - bx
  const cy = 3 * y1
  const by = 3 * (y2 - y1) - cy
  const ay = 1 - cy - by
  const sampleX = (s: number) => ((ax * s + bx) * s + cx) * s
  const sampleY = (s: number) => ((ay * s + by) * s + cy) * s
  const slopeX = (s: number) => (3 * ax * s + 2 * bx) * s + cx

  function solve(x: number): number {
    let s = x
    for (let i = 0; i < 8; i += 1) {
      const error = sampleX(s) - x
      if (Math.abs(error) < 1e-6) return s
      const slope = slopeX(s)
      if (Math.abs(slope) < 1e-6) break
      s -= error / slope
    }
    let lo = 0
    let hi = 1
    s = x
    while (hi - lo > 1e-6) {
      if (sampleX(s) < x) lo = s
      else hi = s
      s = (lo + hi) / 2
    }
    return s
  }

  return (t) => (t <= 0 ? 0 : t >= 1 ? 1 : sampleY(solve(t)))
}

/** Разбирает `cubic-bezier(a, b, c, d)` из токена `--ease-soft`. */
export function parseCubicBezier(value: string): [number, number, number, number] | null {
  const match = /cubic-bezier\(([^)]+)\)/.exec(value)
  if (!match?.[1]) return null
  const parts = match[1].split(',').map((part) => Number.parseFloat(part))
  if (parts.length !== 4 || parts.some((part) => Number.isNaN(part))) return null
  return parts as [number, number, number, number]
}

/** Длительность из токена (`320ms`, `0.32s`) в миллисекундах. */
export function parseDuration(value: string): number | null {
  const match = /^\s*([\d.]+)\s*(ms|s)\s*$/.exec(value)
  if (!match?.[1]) return null
  const amount = Number.parseFloat(match[1])
  return match[2] === 's' ? amount * 1000 : amount
}
