/**
 * Тема схемы: цвета и шрифт читаются из токенов дизайн-системы во время выполнения.
 *
 * bpmn-js рисует SVG с цветами во встроенных стилях, CSS-переменные туда не доходят.
 * Поэтому значения токенов берём через getComputedStyle и приводим к sRGB-hex:
 * токены могут быть в OKLCH, а экспортированный SVG должны открывать и редакторы без CSS Color 4.
 */

/** Какой токен за что отвечает. Имена — контракт дизайн-системы (docs/frontend/styleguide.md). */
export const THEME_TOKENS = {
  /** Заливка фигур (задачи, события, шлюзы, дорожки). */
  fill: '--color-surface',
  /** Линии фигур и стрелок. */
  stroke: '--color-fg-muted',
  /** Подписи. */
  label: '--color-fg',
  /** Фон PNG. */
  background: '--color-surface',
  /** Шрифт подписей. */
  font: '--font-sans',
} as const

/** Если токена нет (дизайн-система не подключена), берём системные цвета браузера — они следуют color-scheme. */
const FALLBACK = {
  fill: 'Canvas',
  stroke: 'GrayText',
  label: 'CanvasText',
  background: 'Canvas',
  font: 'system-ui, sans-serif',
} as const

export interface DiagramTheme {
  fill: string
  stroke: string
  label: string
  background: string
  fontFamily: string
}

export type TokenReader = (token: string) => string

/** Чистая сборка темы из читателя токенов: удобно тестировать без браузера. */
export function resolveTheme(
  read: TokenReader,
  normalize: (color: string) => string = (color) => color,
): DiagramTheme {
  const color = (key: 'fill' | 'stroke' | 'label' | 'background') =>
    normalize(read(THEME_TOKENS[key]).trim() || FALLBACK[key])
  return {
    fill: color('fill'),
    stroke: color('stroke'),
    label: color('label'),
    background: color('background'),
    fontFamily: read(THEME_TOKENS.font).trim() || FALLBACK.font,
  }
}

/** Читает тему с элемента (наследует токены от <html>). */
export function readDiagramTheme(element: Element): DiagramTheme {
  const style = getComputedStyle(element)
  return resolveTheme((token) => style.getPropertyValue(token), normalizeColor)
}

export function sameTheme(a: DiagramTheme, b: DiagramTheme): boolean {
  return (
    a.fill === b.fill &&
    a.stroke === b.stroke &&
    a.label === b.label &&
    a.background === b.background &&
    a.fontFamily === b.fontFamily
  )
}

/** Первое семейство из списка `font-family` без кавычек — для `document.fonts.load`. */
export function primaryFontFamily(fontFamily: string): string {
  const first = fontFamily.split(',')[0] ?? ''
  return first.trim().replace(/^["']|["']$/g, '')
}

let probe: CanvasRenderingContext2D | null | undefined

function getProbe(): CanvasRenderingContext2D | null {
  if (probe === undefined) {
    const canvas = document.createElement('canvas')
    canvas.width = 1
    canvas.height = 1
    probe = canvas.getContext('2d', { willReadFrequently: true })
  }
  return probe
}

function toHex(channel: number): string {
  return channel.toString(16).padStart(2, '0')
}

/**
 * Любой CSS-цвет (OKLCH, системный, именованный) в `#rrggbb` или `#rrggbbaa` в sRGB.
 * Рисуем пиксель на canvas и читаем его: так конвертирует сам браузер, без своей колориметрии.
 * Нераспознанный цвет возвращается как есть.
 */
export function normalizeColor(value: string): string {
  const ctx = getProbe()
  if (!ctx || !value) return value
  ctx.clearRect(0, 0, 1, 1)
  // Невалидное значение fillStyle не меняет — останется прозрачный и вернём исходную строку.
  ctx.fillStyle = 'transparent'
  ctx.fillStyle = value
  ctx.fillRect(0, 0, 1, 1)
  const [r = 0, g = 0, b = 0, a = 0] = ctx.getImageData(0, 0, 1, 1).data
  if (a === 0) return value
  const alpha = a === 255 ? '' : toHex(a)
  return `#${toHex(r)}${toHex(g)}${toHex(b)}${alpha}`
}

/**
 * Следит за сменой темы: атрибут `data-theme` (и `class`) на <html> и системная схема.
 * Возвращает функцию отписки.
 */
export function observeTheme(onChange: () => void): () => void {
  const observer = new MutationObserver(onChange)
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['data-theme', 'class'],
  })
  const media = window.matchMedia?.('(prefers-color-scheme: dark)')
  media?.addEventListener('change', onChange)
  return () => {
    observer.disconnect()
    media?.removeEventListener('change', onChange)
  }
}
