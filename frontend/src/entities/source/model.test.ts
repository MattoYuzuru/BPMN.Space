import { findQuoteRanges, isAcceptedFile, type Source, sourceMeta, splitByRanges } from './model'

const text =
  'Сетевая организация проверяет комплектность заявки.\nЕсли документов не хватает, заявителю направляется уведомление.'

describe('цитаты в источнике', () => {
  it('находит цитату с нестрогими пробелами', () => {
    const [range] = findQuoteRanges(text, [
      { quote: 'заявки. Если документов', kind: 'about', ref: 'q1' },
    ])
    expect(range && text.slice(range.start, range.end)).toBe('заявки.\nЕсли документов')
  })

  it('отбрасывает перекрытия и ненайденное, доказательство важнее повода', () => {
    const ranges = findQuoteRanges(text, [
      { quote: 'проверяет комплектность', kind: 'about', ref: 'q1' },
      { quote: 'проверяет комплектность заявки', kind: 'evidence', ref: 'q2' },
      { quote: 'комплектность', kind: 'trace', ref: 'Task_1' },
      { quote: 'нет в тексте', kind: 'about', ref: 'q3' },
      { quote: 'направляется уведомление', kind: 'trace', ref: 'Task_2' },
    ])
    expect(ranges.map((range) => [range.kind, range.ref])).toEqual([
      ['evidence', 'q2'],
      ['trace', 'Task_2'],
    ])
  })

  it('режет текст на куски с подсветкой', () => {
    const ranges = findQuoteRanges('раз два три', [{ quote: 'два', kind: 'about', ref: 'q' }])
    const parts = splitByRanges('раз два три', ranges)
    expect(parts.map((part) => [part.start, part.text, Boolean(part.range)])).toEqual([
      [0, 'раз ', false],
      [4, 'два', true],
      [7, ' три', false],
    ])
  })
})

describe('метаданные источника', () => {
  const base = { content: 'abc', kind: 'text' } as Source
  it('показывает длительность, размер или объём текста', () => {
    expect(sourceMeta({ ...base, kind: 'voice', duration_sec: 142 })).toBe('2:22')
    expect(sourceMeta({ ...base, kind: 'file', size_bytes: 1331 })).toBe('1,3 КБ')
    expect(sourceMeta(base)).toBe('3 знака')
  })

  it('принимает только поддерживаемые форматы', () => {
    expect(isAcceptedFile('Финансы.DOCX')).toBe(true)
    expect(isAcceptedFile('notes.md')).toBe(true)
    expect(isAcceptedFile('scan.png')).toBe(false)
  })
})
