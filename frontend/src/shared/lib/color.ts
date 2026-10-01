/**
 * Цветовая математика дизайн-системы: перевод OKLCH в sRGB, hex и контраст WCAG 2.x.
 * Используется тестом контраста токенов и живым стайлгайдом (hex считается из токенов,
 * а не хранится руками — поэтому документация не расходится с CSS).
 */

export interface Oklch {
  l: number
  c: number
  h: number
  alpha: number
}

export interface Rgb {
  r: number
  g: number
  b: number
}

const OKLCH_RE =
  /^oklch\(\s*([\d.]+)(%?)\s+([\d.]+)\s+([\d.]+)(?:deg)?\s*(?:\/\s*([\d.]+)(%?))?\s*\)$/i

/** Разбирает строку вида «oklch L C H / A». Возвращает null, если формат другой. */
export function parseOklch(value: string): Oklch | null {
  const match = OKLCH_RE.exec(value.trim())
  if (!match) return null
  const [, l = '0', lPercent, c = '0', h = '0', a, aPercent] = match
  const lightness = Number(l) / (lPercent ? 100 : 1)
  const alpha = a === undefined ? 1 : Number(a) / (aPercent ? 100 : 1)
  return { l: lightness, c: Number(c), h: Number(h), alpha }
}

/** Линейный sRGB без обрезки по гамуту. */
function oklchToLinear({ l, c, h }: Oklch): [number, number, number] {
  const a = c * Math.cos((h * Math.PI) / 180)
  const b = c * Math.sin((h * Math.PI) / 180)
  const l_ = (l + 0.3963377774 * a + 0.2158037573 * b) ** 3
  const m_ = (l - 0.1055613458 * a - 0.0638541728 * b) ** 3
  const s_ = (l - 0.0894841775 * a - 1.291485548 * b) ** 3
  return [
    4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
    -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
    -0.0041960863 * l_ - 0.7034186147 * m_ + 1.707614701 * s_,
  ]
}

const clamp01 = (x: number) => Math.min(1, Math.max(0, x))
const encode = (x: number) => (x <= 0.0031308 ? 12.92 * x : 1.055 * x ** (1 / 2.4) - 0.055)

/** Цвет внутри гамута sRGB (с допуском на округление). */
export function isInSrgbGamut(color: Oklch): boolean {
  return oklchToLinear(color).every((x) => x >= -0.0005 && x <= 1.0005)
}

/** sRGB (0..1, гамма-кодированный), вне гамута — обрезка. */
export function oklchToRgb(color: Oklch): Rgb {
  const [r, g, b] = oklchToLinear(color).map((x) => clamp01(encode(clamp01(x)))) as [
    number,
    number,
    number,
  ]
  return { r, g, b }
}

export function toHex(color: Oklch): string {
  const { r, g, b } = oklchToRgb(color)
  return `#${[r, g, b]
    .map((x) =>
      Math.round(x * 255)
        .toString(16)
        .padStart(2, '0'),
    )
    .join('')}`
}

/** Накладывает полупрозрачный цвет на непрозрачный фон (в sRGB, как делает браузер). */
export function composite(top: Oklch, bottom: Oklch): Rgb {
  const t = oklchToRgb(top)
  const b = oklchToRgb(bottom)
  const a = top.alpha
  return { r: t.r * a + b.r * (1 - a), g: t.g * a + b.g * (1 - a), b: t.b * a + b.b * (1 - a) }
}

const linearize = (x: number) => (x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4)

/** Относительная яркость по WCAG 2.x. */
export function relativeLuminance(rgb: Rgb): number {
  return 0.2126 * linearize(rgb.r) + 0.7152 * linearize(rgb.g) + 0.0722 * linearize(rgb.b)
}

/** Коэффициент контраста WCAG 2.x (1..21). Полупрозрачный передний план накладывается на фон. */
export function contrastRatio(foreground: Oklch, background: Oklch): number {
  const fg = foreground.alpha < 1 ? composite(foreground, background) : oklchToRgb(foreground)
  const y1 = relativeLuminance(fg)
  const y2 = relativeLuminance(oklchToRgb(background))
  const [hi, lo] = y1 > y2 ? [y1, y2] : [y2, y1]
  return (hi + 0.05) / (lo + 0.05)
}

/** Порог WCAG AA: 4.5 для обычного текста, 3 для крупного текста и графики интерфейса. */
export const WCAG_AA_TEXT = 4.5
export const WCAG_AA_NON_TEXT = 3
