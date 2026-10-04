import type { Question } from '@/entities/question'
import {
  formatSummary,
  initialRunView,
  type Run,
  type RunEvent,
  type RunView,
  reduceRun,
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
})

describe('formatSummary', () => {
  it('пишет итог без нулей', () => {
    expect(formatSummary({ resolved: 2, open: 2, new: 1 })).toBe('Решено 2, осталось 2, новых 1')
    expect(formatSummary({ resolved: 0, open: 3, new: 0 })).toBe('Осталось 3')
    expect(formatSummary({ resolved: 0, open: 0, new: 0 })).toBe('Открытых вопросов нет')
  })
})
