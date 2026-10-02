import { contrastRatio, parseOklch, toHex } from './color'
import {
  formatBytes,
  formatClock,
  formatCount,
  formatDuration,
  formatNumber,
  pluralRu,
} from './format'

describe('format', () => {
  it('склоняет по числу', () => {
    const forms = ['вопрос', 'вопроса', 'вопросов'] as const
    expect([1, 2, 5, 11, 21, 104].map((n) => pluralRu(n, forms))).toEqual([
      'вопрос',
      'вопроса',
      'вопросов',
      'вопросов',
      'вопрос',
      'вопроса',
    ])
    expect(formatCount(3, forms)).toBe('3\u00a0вопроса')
  })

  it('разделяет разряды и пишет длительность', () => {
    expect(formatNumber(12345).replace(/\s/g, ' ')).toBe('12 345')
    expect(formatDuration(12_400)).toBe('12\u00a0с')
    expect(formatDuration(65_000)).toBe('1\u00a0мин 05\u00a0с')
  })

  it('пишет длительность записи и размер файла', () => {
    expect(formatClock(7)).toBe('0:07')
    expect(formatClock(142.6)).toBe('2:22')
    expect(formatClock(3725)).toBe('1:02:05')
    expect(formatBytes(812)).toBe('812\u00a0Б')
    expect(formatBytes(1331)).toBe('1,3\u00a0КБ')
    expect(formatBytes(48 * 1024)).toBe('48\u00a0КБ')
    expect(formatBytes(1.4 * 1024 * 1024)).toBe('1,4\u00a0МБ')
  })
})

describe('color', () => {
  it('разбирает OKLCH и считает контраст', () => {
    const white = parseOklch('oklch(1 0 0)')
    const black = parseOklch('oklch(0 0 0)')
    if (!white || !black) throw new Error('не разобрано')
    expect(toHex(white)).toBe('#ffffff')
    expect(contrastRatio(white, black)).toBeCloseTo(21, 1)
    expect(parseOklch('oklch(50% 0.1 250 / 40%)')).toEqual({ l: 0.5, c: 0.1, h: 250, alpha: 0.4 })
    expect(parseOklch('#fff')).toBeNull()
  })
})
