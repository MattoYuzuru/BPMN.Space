import { countByGroup, type Question, questionGroup, shiftSummary, sortQuestions } from './model'

const make = (patch: Partial<Question>): Question => ({
  id: patch.code ?? 'q',
  project_id: 'p',
  code: 'Q-1',
  kind: 'missing_actor',
  severity: 'major',
  status: 'open',
  text: 'Вопрос',
  assumption: 'Допущение',
  element_ids: [],
  created_at: '2026-10-01T10:00:00Z',
  updated_at: '2026-10-01T10:00:00Z',
  ...patch,
})

describe('вопросы', () => {
  it('раскладывает статусы по вкладкам', () => {
    expect(questionGroup('open')).toBe('open')
    expect(questionGroup('answered')).toBe('resolved')
    expect(questionGroup('ignored')).toBe('assumed')
    expect(questionGroup('resolved')).toBe('resolved')
    expect(questionGroup('obsolete')).toBe('resolved')
  })

  it('сортирует: требующие ответа, важность, номер', () => {
    const sorted = sortQuestions([
      make({ code: 'Q-10', severity: 'minor' }),
      make({ code: 'Q-2', severity: 'blocker', status: 'answered' }),
      make({ code: 'Q-3', severity: 'blocker' }),
      make({ code: 'Q-9', severity: 'major' }),
      make({ code: 'Q-4', severity: 'major' }),
    ])
    expect(sorted.map((question) => question.code)).toEqual(['Q-3', 'Q-4', 'Q-9', 'Q-10', 'Q-2'])
  })

  it('отвеченные и решённые — свежие сверху, открытые всегда раньше', () => {
    const sorted = sortQuestions([
      make({ code: 'Q-1', status: 'resolved', updated_at: '2026-10-01T10:00:00Z' }),
      make({ code: 'Q-2', status: 'resolved', updated_at: '2026-10-02T10:00:00Z' }),
      make({ code: 'Q-3', status: 'answered', updated_at: '2026-10-03T10:00:00Z' }),
      make({ code: 'Q-4', status: 'open', updated_at: '2026-10-01T10:00:00Z' }),
    ])
    expect(sorted.map((question) => question.code)).toEqual(['Q-4', 'Q-3', 'Q-2', 'Q-1'])
  })

  it('считает вопросы по вкладкам', () => {
    expect(
      countByGroup([
        make({ status: 'open' }),
        make({ status: 'answered' }),
        make({ status: 'ignored' }),
        make({ status: 'resolved' }),
      ]),
    ).toEqual({ open: 1, assumed: 1, resolved: 2 })
  })
})

describe('shiftSummary (оптимистичная сводка)', () => {
  const summary = { resolved: 1, open: 2, new: 1, ignored: 0, answered: 0 }

  it('переносит вопрос между корзинами', () => {
    expect(shiftSummary(summary, 'open', 'ignored')).toEqual({ ...summary, open: 1, ignored: 1 })
    expect(shiftSummary(summary, 'open', 'answered')).toEqual({ ...summary, open: 1, answered: 1 })
    expect(shiftSummary({ ...summary, ignored: 1 }, 'ignored', 'open')).toEqual({
      ...summary,
      open: 3,
    })
  })

  it('когда «осталось» пусто, уменьшает «новых» и не уходит в минус', () => {
    const empty = { resolved: 0, open: 0, new: 1, ignored: 0, answered: 0 }
    expect(shiftSummary(empty, 'open', 'resolved')).toEqual({ ...empty, new: 0, resolved: 1 })
    expect(shiftSummary({ ...empty, new: 0 }, 'open', 'ignored').new).toBe(0)
    expect(shiftSummary(summary, 'open', 'open')).toBe(summary)
  })
})
