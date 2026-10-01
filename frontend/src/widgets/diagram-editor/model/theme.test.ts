import { primaryFontFamily, resolveTheme, sameTheme, THEME_TOKENS } from './theme'

const TOKENS: Record<string, string> = {
  '--color-surface': ' #ffffff ',
  '--color-fg-muted': '#5b6170',
  '--color-fg': 'oklch(0.232 0.01 265)',
  '--font-sans': '"Geist Variable", ui-sans-serif, sans-serif',
}

describe('resolveTheme', () => {
  it('читает цвета и шрифт из токенов дизайн-системы и обрезает пробелы', () => {
    const theme = resolveTheme((token) => TOKENS[token] ?? '')
    expect(theme).toEqual({
      fill: '#ffffff',
      stroke: '#5b6170',
      label: 'oklch(0.232 0.01 265)',
      background: '#ffffff',
      fontFamily: '"Geist Variable", ui-sans-serif, sans-serif',
    })
  })

  it('пропускает цвета через нормализацию (в браузере — приведение к sRGB-hex)', () => {
    const theme = resolveTheme(
      (token) => TOKENS[token] ?? '',
      (color) => `norm(${color})`,
    )
    expect(theme.label).toBe('norm(oklch(0.232 0.01 265))')
    expect(theme.fontFamily).not.toContain('norm')
  })

  it('без токенов берёт системные цвета браузера, а не сырые значения', () => {
    const theme = resolveTheme(() => '')
    expect(theme).toEqual({
      fill: 'Canvas',
      stroke: 'GrayText',
      label: 'CanvasText',
      background: 'Canvas',
      fontFamily: 'system-ui, sans-serif',
    })
  })

  it('опирается только на имена токенов из контракта', () => {
    expect(Object.values(THEME_TOKENS)).toEqual([
      '--color-surface',
      '--color-fg-muted',
      '--color-fg',
      '--color-surface',
      '--font-sans',
    ])
  })
})

describe('sameTheme и primaryFontFamily', () => {
  it('сравнивает темы по значениям', () => {
    const a = resolveTheme((token) => TOKENS[token] ?? '')
    expect(sameTheme(a, { ...a })).toBe(true)
    expect(sameTheme(a, { ...a, fill: 'black' })).toBe(false)
  })

  it('достаёт первое семейство шрифта без кавычек', () => {
    expect(primaryFontFamily('"Geist Variable", ui-sans-serif')).toBe('Geist Variable')
    expect(primaryFontFamily("'Inter', sans-serif")).toBe('Inter')
    expect(primaryFontFamily('system-ui')).toBe('system-ui')
  })
})
