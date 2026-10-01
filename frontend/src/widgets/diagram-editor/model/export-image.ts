import cyrillicFontUrl from '@fontsource-variable/geist/files/geist-cyrillic-wght-normal.woff2?url'
import latinFontUrl from '@fontsource-variable/geist/files/geist-latin-wght-normal.woff2?url'
import type { Size } from './viewbox'

/**
 * Экспорт картинок. SVG из bpmn-js ссылается на шрифт по имени; вне страницы (файл, <img>, canvas)
 * веб-шрифтов нет, и подписи, размеченные под Geist, разъезжаются в запасном шрифте.
 * Поэтому шрифт встраивается в SVG как data: URL (латиница + кириллица, ≈ 60 КБ в base64).
 */

const EMBEDDED_FAMILY = 'Geist Variable'

/** Подмножества и диапазоны — как в @fontsource-variable/geist. */
const FONT_FACES = [
  {
    url: cyrillicFontUrl,
    range: 'U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116',
  },
  {
    url: latinFontUrl,
    range:
      'U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD',
  },
] as const

/** Ограничения браузеров на размер canvas (Chrome: 16384 по стороне и ~268 Мп по площади). */
const MAX_CANVAS_SIDE = 16_384
const MAX_CANVAS_AREA = 120_000_000

/** Пауза между прогревочной отрисовкой SVG и итоговой: встроенный шрифт успевает загрузиться. */
const FONT_WARMUP_MS = 200

let fontCssPromise: Promise<string> | undefined

function readAsDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(blob)
  })
}

async function fontFace(url: string, range: string): Promise<string> {
  const response = await fetch(url)
  if (!response.ok) throw new Error(`Шрифт не загрузился: ${response.status}`)
  const base64 = (await readAsDataUrl(await response.blob())).replace(/^data:[^,]*,/, '')
  // Встраиваемый в файл @font-face, а не стиль интерфейса: правило raw-font здесь неприменимо.
  return `@font-face{font-family:'${EMBEDDED_FAMILY}';src:url(data:font/woff2;base64,${base64}) format('woff2');font-weight:100 900;font-style:normal;unicode-range:${range}}` // design-lint-ignore
}

/** CSS со встроенным шрифтом. Загружается один раз за сессию; пустая строка, если шрифт подписей не Geist. */
export function loadEmbeddedFontCss(fontFamily: string): Promise<string> {
  if (!fontFamily.includes(EMBEDDED_FAMILY)) return Promise.resolve('')
  fontCssPromise ??= Promise.all(FONT_FACES.map((face) => fontFace(face.url, face.range)))
    .then((faces) => faces.join(''))
    .catch((error: unknown) => {
      fontCssPromise = undefined
      throw error
    })
  return fontCssPromise
}

/** Вставляет <style> сразу после открывающего тега <svg>. */
export function embedStyle(svg: string, css: string): string {
  if (!css) return svg
  return svg.replace(/<svg\b[^>]*>/, (open) => `${open}<style>${css}</style>`)
}

/** Размер SVG по атрибутам width/height корня. */
export function svgSize(svg: string): Size {
  const open = /<svg\b[^>]*>/.exec(svg)?.[0] ?? ''
  const read = (name: string) =>
    Number.parseFloat(new RegExp(`\\s${name}="([\\d.]+)"`).exec(open)?.[1] ?? '')
  const width = read('width')
  const height = read('height')
  if (!(width > 0 && height > 0)) throw new Error('В SVG нет размеров')
  return { width, height }
}

/** Уменьшает масштаб, если картинка не влезет в canvas браузера. */
export function limitScale(size: Size, scale: number): number {
  const bySide = MAX_CANVAS_SIDE / Math.max(size.width, size.height)
  const byArea = Math.sqrt(MAX_CANVAS_AREA / (size.width * size.height))
  return Math.max(0.1, Math.min(scale, bySide, byArea))
}

/** Перевод SVG в PNG через canvas. `background` — CSS-цвет или `undefined` для прозрачного фона. */
export async function rasterizeSvg(svg: string, scale: number, background?: string): Promise<Blob> {
  const size = svgSize(svg)
  const factor = limitScale(size, scale)
  const width = Math.max(1, Math.round(size.width * factor))
  const height = Math.max(1, Math.round(size.height * factor))
  const url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml;charset=utf-8' }))
  try {
    const image = new Image()
    image.src = url
    await image.decode()
    // Шрифт из data: URL внутри SVG-картинки Chrome начинает грузить только при первой отрисовке,
    // а до загрузки текст невидим. Поэтому сначала «прогревочная» отрисовка, пауза — и только потом PNG.
    document.createElement('canvas').getContext('2d')?.drawImage(image, 0, 0, 1, 1)
    await new Promise((resolve) => setTimeout(resolve, FONT_WARMUP_MS))
    const canvas = document.createElement('canvas')
    canvas.width = width
    canvas.height = height
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('Canvas 2D недоступен')
    if (background) {
      ctx.fillStyle = background
      ctx.fillRect(0, 0, width, height)
    }
    ctx.drawImage(image, 0, 0, width, height)
    return await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob(
        (blob) => (blob ? resolve(blob) : reject(new Error('Не удалось собрать PNG'))),
        'image/png',
      )
    })
  } finally {
    URL.revokeObjectURL(url)
  }
}
