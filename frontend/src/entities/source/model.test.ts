import {
  buildSourceTree,
  capabilityInfo,
  capabilityLabel,
  countSourceTree,
  derivationCost,
  derivationLabel,
  descendantIds,
  findQuoteRanges,
  isAcceptedFile,
  isAgentSource,
  limitParts,
  quoteReferences,
  SOURCE_TRUST,
  type Source,
  sourceKindOf,
  sourceMeta,
  sourceTrustInfo,
  splitByRanges,
  splitTimecodes,
  unreadablePagesLabel,
  unreadablePagesText,
} from './model'

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

  it('сохраняет все связи перекрывающихся цитат и не дублирует один вопрос', () => {
    const marks = [
      { quote: 'проверяет комплектность', kind: 'about' as const, ref: 'q1' },
      { quote: 'проверяет комплектность заявки', kind: 'evidence' as const, ref: 'q1' },
      { quote: 'комплектность', kind: 'about' as const, ref: 'q2' },
      { quote: 'комплектность', kind: 'trace' as const, ref: 'Task_1' },
      { quote: 'не найдено', kind: 'about' as const, ref: 'q3' },
    ]
    const [range] = findQuoteRanges(text, marks)
    if (!range) throw new Error('Цитата должна находиться в источнике')
    expect(quoteReferences(text, range, marks).map((ref) => ref.ref)).toEqual([
      'q1',
      'q2',
      'Task_1',
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
    expect(isAcceptedFile('roles.CSV')).toBe(true)
    expect(isAcceptedFile('scan.png')).toBe(false)
  })
})

describe('поддерживаемые форматы и показ длинного текста', () => {
  it('принимает документы Office, аудио и видео', () => {
    for (const name of ['t.XLSX', 'd.pptx', 'm.mp4', 'v.MOV', 'a.m4a', 'r.mkv'])
      expect(isAcceptedFile(name)).toBe(true)
    expect(isAcceptedFile('old.xls')).toBe(false)
  })

  it('показывает длительность записи вместо размера', () => {
    const recording = { kind: 'file', duration_sec: 3725, size_bytes: 9_000_000, content: 'x' }
    expect(sourceMeta(recording as Source)).toBe('1:02:05')
  })

  it('ограничивает только показ: хвост обрезается, цитата остаётся целой', () => {
    const body = 'а'.repeat(100)
    const ranges = [{ start: 40, end: 60, kind: 'about' as const, ref: 'q1' }]
    const parts = splitByRanges(body, ranges)
    const visible = limitParts(parts, 50)
    expect(visible.map((part) => part.text.length)).toEqual([40, 20])
    expect(visible[1]?.range?.ref).toBe('q1')
    expect(limitParts(parts, 10).map((part) => part.text.length)).toEqual([10])
    expect(limitParts(parts, 1000).map((part) => part.text.length)).toEqual([40, 20, 40])
  })
})

describe('дерево материалов', () => {
  const node = (id: string, extra: Partial<Source> = {}): Source => ({
    id,
    project_id: 'p',
    kind: 'text',
    title: id,
    content: '',
    status: 'ready',
    active: true,
    created_at: '2026-11-04T10:00:00Z',
    origin: 'user',
    trust: 'primary',
    edited_by_human: false,
    ...extra,
  })

  it('вкладывает производные в родителя, сироту делает корнем', () => {
    const tree = buildSourceTree([
      node('rec', { kind: 'file', file_name: 'a.mp3' }),
      node('tr', { parent_id: 'rec', origin: 'derived' }),
      node('lost', { parent_id: 'deleted', origin: 'derived' }),
      node('txt'),
    ])
    expect(tree.map((item) => item.source.id)).toEqual(['rec', 'lost', 'txt'])
    expect(tree[0]?.children.map((item) => item.source.id)).toEqual(['tr'])
  })

  it('подписывает запись, расшифровку и провайдера', () => {
    expect(sourceKindOf(node('a', { kind: 'file', file_name: 'a.mp3' })).label).toBe('Аудиозапись')
    expect(sourceKindOf(node('v', { kind: 'file', file_name: 'v.mov' })).label).toBe('Видеозапись')
    const derived = node('t', {
      origin: 'derived',
      derivation: {
        capability: 'speech_to_text',
        provider: 'mock',
        created_at: '2026-11-04T10:00:00Z',
      },
    })
    expect(sourceKindOf(derived).label).toBe('Расшифровка')
    expect(derivationLabel(derived)).toBe('Демо-распознавание')
    expect(derivationLabel(node('u'))).toBeUndefined()
  })

  it('выделяет таймкоды, не теряя текста', () => {
    const text = '[00:00] Начало.\n[1:02:03] Конец.'
    const parts = splitTimecodes(text)
    expect(parts.join('')).toBe(text)
    expect(parts.filter((_, index) => index % 2 === 1)).toEqual(['[00:00]', '[1:02:03]'])
  })

  it('находит детей и внуков без самого корня', () => {
    const ids = descendantIds(
      [node('r'), node('a', { parent_id: 'r' }), node('b', { parent_id: 'a' }), node('x')],
      'r',
    )
    expect([...ids]).toEqual(['a', 'b'])
  })
})

describe('возможности, доверие и дополнительные поля источника', () => {
  const node = (extra: Partial<Source> = {}): Source => ({
    id: 's',
    project_id: 'p',
    kind: 'text',
    title: 'Материал',
    content: '',
    status: 'ready',
    active: true,
    created_at: '2026-11-04T10:00:00Z',
    origin: 'user',
    trust: 'primary',
    edited_by_human: false,
    ...extra,
  })

  it('подписывает любую известную возможность, а незнакомую не показывает сырым кодом', () => {
    expect(capabilityLabel('speech_to_text')).toBe('Расшифровка')
    expect(capabilityLabel('ocr')).toBe('Распознанный текст')
    expect(capabilityLabel('vision')).toBe('Описание изображения')
    expect(capabilityInfo('video_understanding').processing).toBe('Смотрю видео')
    expect(capabilityLabel('brand_new_capability')).toBe('Материал от ИИ')
    expect(capabilityInfo(null).icon).toBe('sparkles')
  })

  it('у каждого уровня доверия есть подпись, короткая метка и пояснение', () => {
    for (const trust of Object.keys(SOURCE_TRUST) as (keyof typeof SOURCE_TRUST)[]) {
      const info = sourceTrustInfo(trust)
      expect(info.label.length).toBeGreaterThan(0)
      expect(info.short.length).toBeGreaterThan(0)
      expect(info.description.length).toBeGreaterThan(0)
    }
    expect(sourceTrustInfo('summary').tone).toBe('amber')
    expect(sourceTrustInfo('agent').label).toBe('От агента')
  })

  it('узнаёт материал агента и показывает стоимость обработки', () => {
    const derived = node({
      origin: 'derived',
      derivation: {
        capability: 'speech_to_text',
        provider: 'deepgram',
        created_at: '2026-11-04T10:00:00Z',
        cost_usd: 0.42,
      },
    })
    expect(isAgentSource(node({ origin: 'agent' }))).toBe(true)
    expect(isAgentSource(derived)).toBe(false)
    expect(derivationCost(derived)).toBe(0.42)
    expect(derivationCost(node())).toBeNull()
  })

  it('называет страницы без текстового слоя', () => {
    expect(unreadablePagesLabel([])).toBeNull()
    expect(unreadablePagesLabel(null)).toBeNull()
    expect(unreadablePagesLabel([2])).toBe('1\u00a0страница без текста')
    expect(unreadablePagesLabel([2, 5])).toBe('2\u00a0страницы без текста')
    expect(unreadablePagesText([12, 15])).toBe(
      'Не прочитан текст страниц: 12, 15. Это сканы без текстового слоя.',
    )
    const many = Array.from({ length: 10 }, (_, index) => index + 1)
    expect(unreadablePagesText(many)).toBe(
      'Не прочитан текст страниц: 1, 2, 3, 4, 5, 6, 7, 8 и ещё 2\u00a0страницы. Это сканы без текстового слоя.',
    )
  })

  it('считает все узлы дерева, а не только корни', () => {
    const tree = buildSourceTree([
      node({ id: 'rec' }),
      node({ id: 'tr', parent_id: 'rec', origin: 'derived' }),
      node({ id: 'frames', parent_id: 'rc' }),
      node({ id: 'txt' }),
    ])
    expect(tree).toHaveLength(3)
    expect(countSourceTree(tree)).toBe(4)
    expect(countSourceTree([])).toBe(0)
  })
})
