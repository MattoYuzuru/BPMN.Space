import type { Question } from '@/entities/question'
import {
  agentSteps,
  formatSummary,
  initialRunView,
  isAgentRun,
  type Run,
  type RunCost,
  type RunEvent,
  type RunView,
  reduceRun,
  runStatusView,
  runSteps,
} from './model'

const run: Run = {
  id: 'run-1',
  project_id: 'p-1',
  mode: 'analyze',
  status: 'queued',
  stage: null,
  stage_label: 'В очереди',
  progress: 0,
  started_at: '2026-10-02T10:00:00Z',
}

const question = (status: Question['status']): Question => ({
  id: 'q-1',
  project_id: 'p-1',
  code: 'Q-1',
  kind: 'missing_actor',
  severity: 'major',
  status,
  text: 'Кто согласует бюджет?',
  assumption: 'Руководитель отдела',
  element_ids: [],
  category: 'business',
  blocking: false,
  created_at: '2026-10-02T10:00:00Z',
  updated_at: '2026-10-02T10:00:00Z',
})

const stage = (id: number, name: 'reading_sources' | 'extracting' | 'reconciling'): RunEvent => ({
  type: 'stage',
  id,
  data: { stage: name, label: name, progress: id / 4 },
})

function play(events: RunEvent[], start = 0): RunView {
  return events.reduce(
    (view, event, index) => reduceRun(view, event, start + (index + 1) * 1000),
    initialRunView(run, start),
  )
}

describe('reduceRun', () => {
  it('ведёт этапы и считает их длительность', () => {
    const view = play([stage(1, 'reading_sources'), stage(2, 'extracting')])
    expect(view.stage).toBe('extracting')
    expect(view.stageStartedAt.reading_sources).toBe(1000)
    expect(view.stageFinishedAt.reading_sources).toBe(2000)
    const steps = runSteps(view)
    expect(steps.map((step) => step.status)).toEqual(['complete', 'current', 'upcoming'])
    expect(steps[0]?.meta).toBe('1 с')
  })

  it('игнорирует повтор истории после переподключения', () => {
    const once = play([stage(1, 'reading_sources'), stage(2, 'extracting')])
    const replayed = reduceRun(once, stage(1, 'reading_sources'), 9000)
    expect(replayed).toBe(once)
    expect(reduceRun(once, stage(2, 'extracting'), 9000)).toBe(once)
  })

  it('собирает вопросы, итог и завершение', () => {
    const summary = { resolved: 2, open: 2, new: 1, ignored: 0, answered: 0 }
    const view = play([
      stage(1, 'reconciling'),
      { type: 'question', id: 2, data: { question: question('resolved') } },
      {
        type: 'question',
        id: 3,
        data: { question: { ...question('open'), id: 'q-2', code: 'Q-2' } },
      },
      { type: 'summary', id: 4, data: summary },
      { type: 'done', id: 5, data: { run: { ...run, status: 'succeeded', summary } } },
    ])
    expect(view.questions.map((item) => item.code)).toEqual(['Q-1', 'Q-2'])
    expect(view.status).toBe('succeeded')
    expect(view.summary).toEqual(summary)
    expect(view.finishedAt).toBe(5000)
    expect(runSteps(view).every((step) => step.status === 'complete')).toBe(true)
  })

  it('показывает ошибку на текущем этапе', () => {
    const view = play([
      stage(1, 'reading_sources'),
      stage(2, 'extracting'),
      { type: 'error', id: 3, data: { message: 'Модель недоступна' } },
      {
        type: 'done',
        id: 4,
        data: { run: { ...run, status: 'failed', error: 'Модель недоступна' } },
      },
    ])
    expect(view.status).toBe('failed')
    const steps = runSteps(view)
    expect(steps[1]).toMatchObject({ status: 'error', description: 'Модель недоступна' })
  })

  it('отличает отменённый прогон от ошибки и не помечает его успешным', () => {
    const view = play([
      stage(1, 'reading_sources'),
      {
        type: 'done',
        id: 2,
        data: {
          run: { ...run, status: 'cancelled', error: 'Прогон отменён участником' },
        },
      },
    ])
    expect(view.status).toBe('cancelled')
    expect(view.progress).toBe(0.25)
    expect(runSteps(view)[0]?.status).toBe('current')
  })

  it('сохраняет предупреждения прогона из начального состояния и из done', () => {
    const warning = 'Часть источников не поместилась в контекст и пропущена'
    expect(initialRunView({ ...run, warnings: [warning] }, 0).warnings).toEqual([warning])
    const view = play([
      {
        type: 'done',
        id: 1,
        data: { run: { ...run, status: 'succeeded', warnings: [warning] } },
      },
    ])
    expect(view.warnings).toEqual([warning])
    expect(play([]).warnings).toEqual([])
  })

  it('для сборки показывает шесть этапов', () => {
    const view = initialRunView({ ...run, mode: 'build' }, 0)
    expect(runSteps(view)).toHaveLength(6)
  })

  it('берёт время начала с сервера для таймера прогона', () => {
    const view = initialRunView(run, 1234)
    expect(view.startedAt).toBe(Date.parse(run.started_at))
  })

  it('быстрый этап не становится секундой, окончание берётся с сервера', () => {
    let view = initialRunView(run, 0)
    view = reduceRun(view, stage(1, 'reading_sources'), 100)
    view = reduceRun(view, stage(2, 'extracting'), 200)
    expect(runSteps(view)[0]?.meta).toBe('менее 1 с')
    view = reduceRun(
      view,
      {
        type: 'done',
        id: 3,
        data: { run: { ...run, status: 'succeeded', finished_at: new Date(300).toISOString() } },
      },
      9000,
    )
    expect(view.finishedAt).toBe(300)
  })
})

describe('formatSummary', () => {
  it('пишет итог без нулей', () => {
    expect(formatSummary({ resolved: 2, open: 2, new: 1 })).toBe('Решено 2, осталось 2, новых 1')
    expect(formatSummary({ resolved: 0, open: 3, new: 0 })).toBe('Осталось 3')
    expect(formatSummary({ resolved: 0, open: 0, new: 0 })).toBe('Открытых вопросов нет')
  })
})

describe('стоимость, бюджет и ожидание прогона', () => {
  const cost: RunCost = {
    calls: 8,
    tokens_in: 120_000,
    tokens_out: 14_000,
    cache_read_tokens: 40_000,
    cache_write_tokens: 9_000,
    cost_usd: 2.71,
    complete: true,
    currency: 'USD',
    by_stage: [
      {
        stage: 'extracting',
        label: 'Извлечение',
        calls: 8,
        cost_usd: 2.71,
        tokens_in: 120_000,
        tokens_out: 14_000,
        cache_read_tokens: 40_000,
        cache_write_tokens: 9_000,
      },
    ],
  }
  const technical = (blocking: boolean): Question => ({
    ...question('open'),
    id: 'tq-1',
    code: 'TQ-1',
    kind: 'budget_reached',
    category: 'technical',
    blocking,
    actions: [{ kind: 'raise_budget', label: 'Поднять бюджет' }],
    text: 'Бюджет прогона исчерпан',
  })

  it('потраченное приходит событием usage и остаётся в состоянии', () => {
    const view = play([{ type: 'usage', id: 1, data: cost }])
    expect(view.cost?.cost_usd).toBe(2.71)
    expect(view.budget).toBeNull()
  })

  it('блокирующий технический вопрос переводит прогон в waiting, этап возвращает в running', () => {
    const waiting = play([
      stage(1, 'reading_sources'),
      { type: 'question', id: 2, data: { question: technical(true) } },
    ])
    expect(waiting.status).toBe('waiting')
    expect(waiting.questions.map((item) => item.id)).toEqual(['tq-1'])
    const resumed = reduceRun(waiting, stage(3, 'extracting'), 9000)
    expect(resumed.status).toBe('running')
  })

  it('неблокирующий технический вопрос не останавливает прогон', () => {
    const view = play([{ type: 'question', id: 1, data: { question: technical(false) } }])
    expect(view.status).toBe('running')
  })

  it('начальное состояние знает waiting, стоимость и бюджет профиля', () => {
    const view = initialRunView(
      {
        ...run,
        status: 'waiting',
        stage_label: 'Ждёт вашего действия',
        cost,
        profile: { budget: { cost_usd: 10, tokens: null } },
      },
      Date.now(),
    )
    expect(runStatusView('waiting')).toBe('waiting')
    expect(view.status).toBe('waiting')
    expect(view.finishedAt).toBeNull()
    expect(view.cost?.cache_read_tokens).toBe(40_000)
    expect(view.budget).toEqual({ cost_usd: 10, tokens: null })
  })

  it('done с ожиданием не закрывает карточку, а обычный done добавляет стоимость', () => {
    const waiting = play([
      {
        type: 'done',
        id: 1,
        data: { run: { ...run, status: 'waiting', cost } },
      },
    ])
    expect(waiting.status).toBe('waiting')
    expect(waiting.finishedAt).toBeNull()
    expect(waiting.cost?.calls).toBe(8)

    const finished = play([
      {
        type: 'done',
        id: 1,
        data: { run: { ...run, status: 'succeeded', finished_at: '2026-10-02T10:01:00Z', cost } },
      },
    ])
    expect(finished.status).toBe('succeeded')
    expect(finished.cost?.cost_usd).toBe(2.71)
  })
})

describe('агентный режим RFC-0004', () => {
  const agentCost = {
    tokens_in: 1000,
    tokens_out: 500,
    cache_read_tokens: 0,
    cache_write_tokens: 0,
    calls: 5,
    cost_usd: 1.2,
    complete: true,
    currency: 'USD' as const,
    by_stage: [
      {
        stage: 'agent',
        label: 'Агентное чтение',
        calls: 3,
        tokens_in: 800,
        tokens_out: 400,
        cache_read_tokens: 0,
        cache_write_tokens: 0,
        cost_usd: 1,
      },
      {
        stage: 'structure',
        label: 'Сборка схемы',
        calls: 2,
        tokens_in: 200,
        tokens_out: 100,
        cache_read_tokens: 0,
        cache_write_tokens: 0,
        cost_usd: 0.2,
      },
    ],
  }

  it('берёт режим и лимит шагов из профиля прогона', () => {
    const view = initialRunView(
      {
        ...run,
        status: 'running',
        profile: { mode: 'agent', max_steps: 12, budget: { tokens: 50_000 } },
        cost: agentCost,
      },
      Date.now(),
    )
    expect(view.profileMode).toBe('agent')
    expect(view.maxSteps).toBe(12)
    expect(isAgentRun(view)).toBe(true)
    expect(agentSteps(view.cost)).toBe(3)
  })

  it('конвейерный прогон и done без профиля остаются pipeline', () => {
    const view = initialRunView(run, Date.now())
    expect(view.profileMode).toBe('pipeline')
    expect(isAgentRun(view)).toBe(false)
    expect(agentSteps(null)).toBe(0)
    const done = play([
      {
        type: 'done',
        id: 1,
        data: {
          run: {
            ...run,
            status: 'succeeded',
            finished_at: '2026-10-02T10:01:00Z',
            profile: { mode: 'agent', max_steps: 6 },
          },
        },
      },
    ])
    expect(done.profileMode).toBe('agent')
    expect(done.maxSteps).toBe(6)
  })
})
