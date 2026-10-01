/// <reference types="node" />
/**
 * Проверка токенов: контраст WCAG AA в обеих темах, полнота тёмной темы, контракт имён,
 * попадание палитры в гамут sRGB. Значения читаются из tokens.css — тест не даёт им разойтись.
 */
import { existsSync, readFileSync } from 'node:fs'
import { resolve as resolvePath } from 'node:path'
import {
  contrastRatio,
  isInSrgbGamut,
  type Oklch,
  parseOklch,
  WCAG_AA_NON_TEXT,
  WCAG_AA_TEXT,
} from '@/shared/lib/color'

// CSS-импорты в тестах отключены, читаем файл. Vitest запускают из frontend/ или из корня.
const TOKENS = 'src/shared/styles/tokens.css'
const css = readFileSync(
  existsSync(resolvePath(process.cwd(), TOKENS))
    ? resolvePath(process.cwd(), TOKENS)
    : resolvePath(process.cwd(), 'frontend', TOKENS),
  'utf8',
)

function block(selectorStart: string): Record<string, string> {
  const start = css.indexOf(selectorStart)
  if (start < 0) throw new Error(`Нет блока ${selectorStart}`)
  const open = css.indexOf('{', start)
  const close = css.indexOf('\n}', open)
  const body = css.slice(open + 1, close).replace(/\/\*[\s\S]*?\*\//g, '')
  const vars: Record<string, string> = {}
  for (const match of body.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
    vars[match[1] as string] = (match[2] as string).replace(/\s+/g, ' ').trim()
  }
  return vars
}

const palette = block(':root {')
const light = block(':root,\n[data-theme="light"] {')
const dark = block('[data-theme="dark"] {')

function resolve(theme: Record<string, string>, name: string): Oklch {
  let value = theme[`--color-${name}`]
  if (!value) throw new Error(`Нет токена --color-${name}`)
  const ref = /^var\((--palette-[\w-]+)\)$/.exec(value)
  if (ref) value = palette[ref[1] as string]
  const color = value ? parseOklch(value) : null
  if (!color) throw new Error(`Не разобран цвет ${name}: ${value}`)
  return color
}

const THEMES = { светлая: light, тёмная: dark }
const SURFACES = ['bg', 'bg-subtle', 'surface', 'surface-raised']
const TEXT = ['fg', 'fg-muted', 'fg-subtle', 'accent-fg', 'amber-fg', 'success-fg', 'danger-fg']

/** Имена из контракта между агентами (shared-conventions): их нельзя терять и переименовывать. */
const CONTRACT = [
  'bg',
  'bg-subtle',
  'surface',
  'surface-raised',
  'overlay',
  'border',
  'border-strong',
  'fg',
  'fg-muted',
  'fg-subtle',
  'fg-on-accent',
  'accent',
  'accent-hover',
  'accent-subtle',
  'accent-fg',
  'amber',
  'amber-subtle',
  'amber-fg',
  'success',
  'success-subtle',
  'success-fg',
  'danger',
  'danger-subtle',
  'danger-fg',
  'focus-ring',
]

describe.each(Object.entries(THEMES))('тема %s', (_, theme) => {
  it.each(TEXT.flatMap((fg) => SURFACES.map((bg) => [fg, bg])))(
    'текст %s на %s — не меньше 4.5:1',
    (fg, bg) => {
      expect(contrastRatio(resolve(theme, fg), resolve(theme, bg))).toBeGreaterThanOrEqual(
        WCAG_AA_TEXT,
      )
    },
  )

  it.each([
    ['fg-on-accent', 'accent'],
    ['fg-on-accent', 'accent-hover'],
    ['fg-on-accent', 'danger'],
    ['fg-on-accent', 'danger-hover'],
    ['accent-fg', 'accent-subtle'],
    ['amber-fg', 'amber-subtle'],
    ['success-fg', 'success-subtle'],
    ['danger-fg', 'danger-subtle'],
  ])('текст %s на заливке %s — не меньше 4.5:1', (fg, bg) => {
    expect(contrastRatio(resolve(theme, fg), resolve(theme, bg))).toBeGreaterThanOrEqual(
      WCAG_AA_TEXT,
    )
  })

  it.each(
    ['accent', 'amber', 'success', 'danger', 'focus-ring', 'control'].flatMap((fg) =>
      ['bg', 'surface'].map((bg) => [fg, bg]),
    ),
  )('графика %s на %s — не меньше 3:1', (fg, bg) => {
    expect(contrastRatio(resolve(theme, fg), resolve(theme, bg))).toBeGreaterThanOrEqual(
      WCAG_AA_NON_TEXT,
    )
  })

  it('содержит все имена из контракта', () => {
    for (const name of CONTRACT) expect(theme[`--color-${name}`], name).toBeDefined()
  })
})

describe('палитра', () => {
  it('тёмная тема переопределяет каждый семантический токен светлой', () => {
    const lightNames = Object.keys(light).filter((name) => name.startsWith('--color-'))
    const darkNames = Object.keys(dark).filter((name) => name.startsWith('--color-'))
    expect(darkNames.sort()).toEqual(lightNames.sort())
  })

  it('все ступени шкал лежат в гамуте sRGB', () => {
    const outOfGamut = Object.entries(palette)
      .filter(([name]) => name.startsWith('--palette-'))
      .filter(([, value]) => {
        const color = parseOklch(value)
        return !color || !isInSrgbGamut(color)
      })
      .map(([name]) => name)
    expect(outOfGamut).toEqual([])
  })

  it('каждый семантический токен Tailwind зарегистрирован в @theme', () => {
    for (const name of Object.keys(light).filter((n) => n.startsWith('--color-'))) {
      expect(css).toContain(`${name}: var(${name});`)
    }
  })
})
