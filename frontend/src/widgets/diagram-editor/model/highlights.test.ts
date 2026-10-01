import { diffMarkers, HIGHLIGHT_MARKERS, planMarkers, sameHighlights } from './highlights'

describe('planMarkers', () => {
  it('раскладывает подсветку по элементам, элемент может нести несколько маркеров', () => {
    const plan = planMarkers({
      assumptions: ['Task_A', 'Flow_B'],
      selected: ['Task_A'],
      added: ['Task_C', ''],
    })
    expect([...plan.keys()]).toEqual(['Task_A', 'Flow_B', 'Task_C'])
    expect([...(plan.get('Task_A') ?? [])]).toEqual(['hl-assumption', 'hl-selected'])
    expect([...(plan.get('Task_C') ?? [])]).toEqual(['hl-added'])
  })

  it('пустая и частичная подсветка — пустой план без падений', () => {
    expect(planMarkers(undefined).size).toBe(0)
    expect(planMarkers({ selected: [] }).size).toBe(0)
  })

  it('маркеры с префиксом, чтобы не конфликтовать с классами diagram-js', () => {
    for (const marker of Object.values(HIGHLIGHT_MARKERS)) expect(marker).toMatch(/^hl-/)
    expect(Object.values(HIGHLIGHT_MARKERS)).not.toContain('selected')
  })
})

describe('diffMarkers', () => {
  it('снимает только исчезнувшие маркеры и добавляет только новые', () => {
    const prev = planMarkers({ assumptions: ['A', 'B'], selected: ['C'] })
    const next = planMarkers({ assumptions: ['B'], selected: ['A'], added: ['D'] })
    const { add, remove } = diffMarkers(prev, next)
    expect(remove).toEqual([
      ['A', 'hl-assumption'],
      ['C', 'hl-selected'],
    ])
    expect(add).toEqual([
      ['A', 'hl-selected'],
      ['D', 'hl-added'],
    ])
  })

  it('одинаковые планы — без операций (нет мигания)', () => {
    const plan = planMarkers({ selected: ['X'] })
    expect(diffMarkers(plan, planMarkers({ selected: ['X'] }))).toEqual({ add: [], remove: [] })
  })

  it('после переимпорта (пустой предыдущий план) вешает всё заново', () => {
    const next = planMarkers({ assumptions: ['A'], added: ['B'] })
    expect(diffMarkers(new Map(), next).add).toHaveLength(2)
  })
})

describe('sameHighlights', () => {
  it('сравнивает по содержимому, а не по ссылке', () => {
    expect(sameHighlights({ selected: ['A'] }, { selected: ['A'], assumptions: [] })).toBe(true)
    expect(sameHighlights(undefined, {})).toBe(true)
    expect(sameHighlights({ selected: ['A'] }, { selected: ['B'] })).toBe(false)
    expect(sameHighlights({ added: ['A', 'B'] }, { added: ['A'] })).toBe(false)
  })
})
