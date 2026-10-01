import { embedStyle, limitScale, svgSize } from './export-image'

const SVG =
  '<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg" width="3092.5" height="1210" viewBox="0 0 3092.5 1210"><g/></svg>'

describe('экспорт картинок', () => {
  it('вставляет стиль сразу после открывающего тега svg', () => {
    const result = embedStyle(SVG, '@font-face{}')
    expect(result).toContain('viewBox="0 0 3092.5 1210"><style>@font-face{}</style><g/>')
    expect(embedStyle(SVG, '')).toBe(SVG)
  })

  it('читает размер SVG и отказывается работать без него', () => {
    expect(svgSize(SVG)).toEqual({ width: 3092.5, height: 1210 })
    expect(() => svgSize('<svg viewBox="0 0 1 1"/>')).toThrow()
  })

  it('уменьшает масштаб PNG, если canvas браузера не вместит картинку', () => {
    expect(limitScale({ width: 3000, height: 1200 }, 2)).toBe(2)
    const huge = { width: 12_000, height: 3000 }
    const scale = limitScale(huge, 2)
    expect(huge.width * scale).toBeLessThanOrEqual(16_384)
    expect(huge.width * huge.height * scale * scale).toBeLessThanOrEqual(120_000_000)
  })
})
