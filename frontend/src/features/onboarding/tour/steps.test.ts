import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { OnboardingSignal } from '@/shared/lib/onboarding-signals'
import type { TourContext } from './context'
import { resolveView } from './machine'
import { type RunResult, resetTourSession, useTourSession } from './session'
import { RUN_GIVE_UP_MS, RUN_SLOW_MS, STEP_KEYS, tourSteps } from './steps'
import { startTour, stopTour } from './store'
import type { TourApi, TourStep } from './types'

const step = (key: string): TourStep<TourContext> => {
  const found = tourSteps.find((item) => item.key === key)
  if (!found) throw new Error(`нет шага ${key}`)
  return found
}

function makeCtx(patch: Partial<Record<string, unknown>> = {}): TourContext {
  const ui = {
    expandPanel: vi.fn(),
    showOpenQuestions: vi.fn(),
    setTextSuggestion: vi.fn(),
    interceptCreate: vi.fn(),
    closeDialogs: vi.fn(),
    closeShareDialog: vi.fn(),
    openChecklist: vi.fn(),
  }
  return {
    projectId: 'p1',
    loaded: true,
    deleted: false,
    firstTitle: 'Мой первый процесс',
    sources: 2,
    processing: 0,
    runActive: false,
    queued: false,
    stage: null,
    result: null,
    openQuestionIds: ['q1', 'q2'],
    pickedId: 'q1',
    shareCreated: false,
    present: {
      createSubmit: false,
      textContent: false,
      voiceCapture: false,
      shareCreate: false,
      shareCopy: false,
    },
    textSuggestion: 'Подсказка',
    ui,
    ops: { restart: vi.fn().mockResolvedValue(undefined), retryRun: vi.fn() },
    ...patch,
  } as TourContext
}

const result = (patch: Partial<RunResult> = {}): RunResult => ({
  status: 'succeeded',
  openQuestions: 2,
  hasDiagram: true,
  ...patch,
})

function viewOf(key: string, ctx: TourContext, extra: { elapsedMs?: number; page?: number } = {}) {
  return resolveView(step(key), {
    ctx,
    elapsedMs: extra.elapsedMs ?? 0,
    seen: {},
    page: extra.page ?? 0,
  })
}

const api = (): TourApi => ({
  next: vi.fn(),
  back: vi.fn(),
  skipStep: vi.fn(),
  goto: vi.fn(),
  finish: vi.fn(),
})

describe('сценарий тура', () => {
  it('содержит 11 шагов с ключами бэкенда в порядке эпика', () => {
    expect(tourSteps.map((item) => item.key)).toEqual([...STEP_KEYS])
    expect(tourSteps.map((item) => item.chapter)).toEqual([
      'sources',
      'sources',
      'sources',
      'sources',
      'questions',
      'questions',
      'questions',
      'questions',
      'diagram',
      'diagram',
      null,
    ])
  })

  it('тексты страниц не длиннее 160 символов и без восклицаний', () => {
    for (const item of tourSteps) {
      for (const page of item.pages) {
        expect(page.text.length, `${item.key}: ${page.text}`).toBeLessThanOrEqual(160)
        expect(page.text).not.toContain('!')
      }
    }
  })

  it('экраны: проекты для шага 1, рабочее место учебного проекта для остальных, финал без экрана', () => {
    const ctx = makeCtx()
    expect(step('project.create').route?.(ctx)).toMatchObject({ to: '/' })
    expect(step('sources.sample').route?.(ctx)).toEqual({
      to: '/projects/$projectId',
      params: { projectId: 'p1' },
    })
    expect(step('sources.sample').route?.(makeCtx({ projectId: null }))).toBeUndefined()
    expect(step('finish').route).toBeUndefined()
  })

  describe('якоря', () => {
    const anchorOf = (key: string, ctx: TourContext) => {
      const anchor = step(key).anchor
      return typeof anchor === 'function' ? anchor(ctx) : anchor
    }

    it('шаг 1: кнопка «Новый проект», затем «Создать проект» в окне', () => {
      expect(anchorOf('project.create', makeCtx())).toBe('projects.new')
      const open = makeCtx({ present: { ...makeCtx().present, createSubmit: true } })
      expect(anchorOf('project.create', open)).toBe('create.submit')
    })

    it('шаг 3 и 4: кнопка меню, пока окно не открыто; поле или запись — когда открыто', () => {
      expect(anchorOf('sources.text', makeCtx())).toBe('sources.add')
      expect(
        anchorOf('sources.text', makeCtx({ present: { ...makeCtx().present, textContent: true } })),
      ).toBe('source-text.content')
      expect(anchorOf('sources.voice', makeCtx())).toBe('sources.add')
      expect(
        anchorOf(
          'sources.voice',
          makeCtx({ present: { ...makeCtx().present, voiceCapture: true } }),
        ),
      ).toBe('voice.capture')
    })

    it('шаг 7: кнопки внутри первой открытой карточки по data-question-id; шаг 8 — другая карточка', () => {
      expect(anchorOf('question.answer', makeCtx())).toEqual({
        selector:
          '[data-question-id="q1"] [data-tour="answer.composer"], [data-question-id="q1"] [data-tour="question.answer"]',
      })
      expect(anchorOf('question.ignore', makeCtx())).toEqual({
        selector: '[data-question-id="q2"] [data-tour="question.ignore"]',
      })
      // Шаг 7 подсвечивал q2 (его пропустили): в шаге 8 берём другой открытый.
      expect(
        anchorOf('question.ignore', makeCtx({ openQuestionIds: ['q1', 'q2'], pickedId: 'q2' })),
      ).toEqual({ selector: '[data-question-id="q1"] [data-tour="question.ignore"]' })
      // До закрепления вопроса подсвечиваем первый открытый; открытых нет — по центру.
      expect(anchorOf('question.answer', makeCtx({ pickedId: null }))).toEqual({
        selector:
          '[data-question-id="q1"] [data-tour="answer.composer"], [data-question-id="q1"] [data-tour="question.answer"]',
      })
      expect(
        anchorOf('question.answer', makeCtx({ pickedId: null, openQuestionIds: [] })),
      ).toBeUndefined()
    })

    it('шаг 9: холст, затем симуляция, затем скачивание', () => {
      expect(step('diagram.tour').pages.map((page) => page.anchor)).toEqual([
        'diagram.canvas',
        'diagram.canvas',
        'header.download',
      ])
      expect(step('diagram.tour').pages[0]?.allowOutside).toBe(true)
      expect(step('diagram.tour').pages[1]).toMatchObject({
        cardAnchor: 'diagram.simulation',
        allowOutside: true,
      })
    })

    it('шаг 10: «Поделиться», затем «Создать ссылку», затем «Копировать ссылку»', () => {
      expect(anchorOf('share.create', makeCtx())).toBe('share.open')
      const open = makeCtx({ present: { ...makeCtx().present, shareCreate: true } })
      expect(anchorOf('share.create', open)).toBe('share.create')
      expect(anchorOf('share.create', makeCtx({ shareCreated: true }))).toBe('share.copy')
    })
  })

  describe('завершение шагов-действий', () => {
    const signal = (item: OnboardingSignal, key: string, ctx = makeCtx()) =>
      step(key).until?.(item, ctx)

    it('источники: пример — любой источник, текст и голос — свой вид', () => {
      expect(signal({ type: 'source.added', kind: 'file' }, 'sources.sample')).toBe(true)
      expect(signal({ type: 'source.added', kind: 'text' }, 'sources.text')).toBe(true)
      expect(signal({ type: 'source.added', kind: 'file' }, 'sources.text')).toBe(false)
      expect(signal({ type: 'source.added', kind: 'voice' }, 'sources.voice')).toBe(true)
      expect(signal({ type: 'source.added', kind: 'text' }, 'sources.voice')).toBe(false)
    })

    it('шаг 1 — проект создан; шаг 7 и 8 — ответ и игнор', () => {
      expect(signal({ type: 'project.created', id: 'p' }, 'project.create')).toBe(true)
      expect(signal({ type: 'question.answered', id: 'q' }, 'question.answer')).toBe(true)
      expect(signal({ type: 'question.ignored', id: 'q' }, 'question.ignore')).toBe(true)
      expect(signal({ type: 'question.ignored', id: 'q' }, 'question.answer')).toBe(false)
    })

    it('шаг 5: прогон уже идёт — шаг засчитан по данным', () => {
      expect(step('run.start').doneWhen?.(makeCtx({ runActive: true }))).toBe(true)
      expect(step('run.start').doneWhen?.(makeCtx())).toBe(false)
      expect(signal({ type: 'run.started', id: 'r', projectId: 'p1' }, 'run.start')).toBe(true)
    })

    it('шаг 10: ссылка создана и окно закрыто', () => {
      const created = makeCtx({ shareCreated: true })
      expect(step('share.create').doneWhen?.(created)).toBe(true)
      const open = makeCtx({
        shareCreated: true,
        present: { ...makeCtx().present, shareCopy: true },
      })
      expect(step('share.create').doneWhen?.(open)).toBe(false)
      expect(step('share.create').doneWhen?.(makeCtx())).toBe(false)
    })
  })

  describe('шаг 5: ожидание разбора', () => {
    it('пока документ разбирается — «ждём» без подсветки', () => {
      const view = viewOf('run.start', makeCtx({ processing: 1 }))
      expect(view.tone).toBe('waiting')
      expect(view.anchor).toBeNull()
      expect(view.text).toBe('Ждём, пока документ разберётся…')
    })

    it('без источников — подсказка добавить источник на кнопке меню', () => {
      const view = viewOf('run.start', makeCtx({ sources: 0 }))
      expect(view.anchor).toBe('sources.add')
    })

    it('обычный вид — кнопка «Построить схему»', () => {
      const view = viewOf('run.start', makeCtx())
      expect(view.anchor).toBe('run.build')
      expect(view.tone).toBe('default')
    })
  })

  describe('шаг 6: ход прогона и сбои', () => {
    it('страницы по этапам, очередь после паузы', () => {
      expect(viewOf('run.wait', makeCtx({ stage: 'reading_sources' })).text).toBe(
        'Читаем источники…',
      )
      expect(viewOf('run.wait', makeCtx({ stage: 'extracting' })).text).toContain('Ищем неясности')
      expect(viewOf('run.wait', makeCtx({ stage: 'structuring' })).text).toContain('Собираем схему')
      expect(viewOf('run.wait', makeCtx({ queued: true }), { elapsedMs: 0 }).text).toBe(
        'Читаем источники…',
      )
      expect(viewOf('run.wait', makeCtx({ queued: true }), { elapsedMs: 4000 }).text).toBe(
        'Модель занята другими запросами — прогон начнётся, как только она освободится.',
      )
    })

    it('через 60 с — успокаивающий текст, через 150 с — «Пропустить главу»', () => {
      const early = viewOf('run.wait', makeCtx(), { elapsedMs: RUN_SLOW_MS - 1 })
      expect(early.text).not.toContain('дольше обычного')
      expect(early.actions).toBeUndefined()
      const slow = viewOf('run.wait', makeCtx(), { elapsedMs: RUN_SLOW_MS })
      expect(slow.text).toBe('Модель думает дольше обычного — это нормально.')
      expect(slow.actions).toBeUndefined()
      const late = viewOf('run.wait', makeCtx(), { elapsedMs: RUN_GIVE_UP_MS })
      expect(late.actions?.map((action) => action.label)).toEqual(['Пропустить главу'])
      expect(step('run.wait').ticks).toEqual(expect.arrayContaining([RUN_SLOW_MS, RUN_GIVE_UP_MS]))
    })

    it('«Пропустить главу» ведёт к шагу 10', () => {
      const late = viewOf('run.wait', makeCtx(), { elapsedMs: RUN_GIVE_UP_MS })
      const tour = api()
      late.actions?.[0]?.run(tour)
      expect(tour.goto).toHaveBeenCalledWith('share.create')
    })

    it('упал без вопросов: «Повторить» запускает прогон и возвращает к шагу 6, «Пропустить главу» — к шагу 10', () => {
      const ctx = makeCtx({
        result: result({ status: 'failed', openQuestions: 0, hasDiagram: false }),
      })
      const view = viewOf('run.wait', ctx)
      expect(view.tone).toBe('error')
      expect(view.text).toBe('Модель не ответила. Попробуем ещё раз?')
      expect(view.actions?.map((action) => action.label)).toEqual(['Повторить', 'Пропустить главу'])
      const tour = api()
      view.actions?.[0]?.run(tour)
      expect(ctx.ops.retryRun).toHaveBeenCalled()
      expect(tour.goto).toHaveBeenCalledWith('run.wait')
    })

    it('вопросов нет, схема есть: объясняем и ждём «Далее»', () => {
      const ctx = makeCtx({ result: result({ openQuestions: 0 }) })
      const view = viewOf('run.wait', ctx)
      expect(view.text).toContain('вопросов нет')
      const tour = api()
      view.actions?.[0]?.run(tour)
      expect(tour.next).toHaveBeenCalled()
    })

    it('вопросы есть — шаг завершается по сигналу и по данным, пустые итоги — нет', () => {
      const until = step('run.wait').until
      const finished = (patch: Partial<Extract<OnboardingSignal, { type: 'run.finished' }>>) =>
        ({
          type: 'run.finished',
          status: 'succeeded',
          openQuestions: 2,
          hasDiagram: true,
          ...patch,
        }) as OnboardingSignal
      expect(until?.(finished({}), makeCtx())).toBe(true)
      expect(until?.(finished({ status: 'failed', openQuestions: 1 }), makeCtx())).toBe(true)
      expect(until?.(finished({ openQuestions: 0 }), makeCtx())).toBe(false)
      expect(step('run.wait').doneWhen?.(makeCtx({ result: result() }))).toBe(true)
      expect(step('run.wait').doneWhen?.(makeCtx({ result: result({ openQuestions: 0 }) }))).toBe(
        false,
      )
      expect(step('run.wait').doneWhen?.(makeCtx())).toBe(false)
    })
  })

  describe('пропуск шагов по итогу прогона', () => {
    const skipped = (key: string, ctx: TourContext) => step(key).skipIf?.(ctx) ?? false

    it('пока итог неизвестен или данные грузятся — ничего не пропускаем', () => {
      for (const key of ['question.answer', 'question.ignore', 'diagram.tour']) {
        expect(skipped(key, makeCtx({ result: null }))).toBe(false)
      }
    })

    it('succeeded с двумя вопросами — все шаги на месте', () => {
      const ctx = makeCtx({ result: result() })
      expect(skipped('question.answer', ctx)).toBe(false)
      expect(skipped('question.ignore', ctx)).toBe(false)
      expect(skipped('diagram.tour', ctx)).toBe(false)
    })

    it('failed с вопросами — шаги 7–8, шаг 9 пропущен', () => {
      const ctx = makeCtx({ result: result({ status: 'failed', hasDiagram: false }) })
      expect(skipped('question.answer', ctx)).toBe(false)
      expect(skipped('question.ignore', ctx)).toBe(false)
      expect(skipped('diagram.tour', ctx)).toBe(true)
    })

    it('вопросов нет — шаги 7–8 пропущены, схема показана', () => {
      const ctx = makeCtx({ result: result({ openQuestions: 0 }) })
      expect(skipped('question.answer', ctx)).toBe(true)
      expect(skipped('question.ignore', ctx)).toBe(true)
      expect(skipped('diagram.tour', ctx)).toBe(false)
    })

    it('вопрос один — шаг 8 пропущен', () => {
      const ctx = makeCtx({ result: result({ openQuestions: 1 }) })
      expect(skipped('question.answer', ctx)).toBe(false)
      expect(skipped('question.ignore', ctx)).toBe(true)
    })
  })

  describe('шаг 4: микрофон', () => {
    it('отказ или отсутствие микрофона — текст про голосовой пример и «Пропустить шаг»', () => {
      const denied = resolveView(step('sources.voice'), {
        ctx: makeCtx(),
        elapsedMs: 0,
        seen: { 'voice.permission-denied': { type: 'voice.permission-denied' } },
        page: 0,
      })
      expect(denied.text).toBe('Ничего страшного — в «Примерах» есть готовая голосовая заметка.')
      expect(denied.actions?.map((action) => action.label)).toEqual(['Пропустить шаг'])
      const missing = resolveView(step('sources.voice'), {
        ctx: makeCtx(),
        elapsedMs: 0,
        seen: { 'voice.unavailable': { type: 'voice.unavailable' } },
        page: 0,
      })
      expect(missing.text).toContain('готовая голосовая заметка')
    })
  })

  describe('подготовка экрана', () => {
    it('шаги 2–4 разворачивают «Источники», шаги 7–8 — «Вопросы» и вкладку «Открытые»', () => {
      for (const key of ['sources.sample', 'sources.text', 'sources.voice']) {
        const ctx = makeCtx()
        step(key).prepare?.(ctx)
        expect(ctx.ui.expandPanel).toHaveBeenCalledWith('sources')
      }
      for (const key of ['question.answer', 'question.ignore']) {
        const ctx = makeCtx()
        step(key).prepare?.(ctx)
        expect(ctx.ui.expandPanel).toHaveBeenCalledWith('questions')
        expect(ctx.ui.showOpenQuestions).toHaveBeenCalled()
      }
    })

    it('шаг 3 включает подсказку и убирает её при выходе', () => {
      const ctx = makeCtx()
      const cleanup = step('sources.text').prepare?.(ctx)
      expect(ctx.ui.setTextSuggestion).toHaveBeenCalledWith('Подсказка')
      cleanup?.()
      expect(ctx.ui.setTextSuggestion).toHaveBeenLastCalledWith(null)
    })

    it('шаг 1 подменяет открытие диалога и возвращает всё при выходе', () => {
      const ctx = makeCtx()
      const cleanup = step('project.create').prepare?.(ctx)
      const title = vi.mocked(ctx.ui.interceptCreate).mock.calls[0]?.[0]
      expect(title?.()).toBe('Мой первый процесс')
      cleanup?.()
      expect(ctx.ui.interceptCreate).toHaveBeenLastCalledWith(null)
    })

    it('шаг 5 закрывает диалоги источников', () => {
      const ctx = makeCtx()
      step('run.start').prepare?.(ctx)
      expect(ctx.ui.closeDialogs).toHaveBeenCalled()
    })
  })

  describe('учебный проект удалён', () => {
    it('любой шаг после создания предлагает «Начать заново» или «Завершить»', () => {
      const ctx = makeCtx({ deleted: true })
      for (const key of STEP_KEYS.slice(1, -1)) {
        const view = viewOf(key, ctx)
        expect(view.title).toBe('Учебный проект удалён')
        expect(view.anchor).toBeNull()
        expect(view.actions?.map((action) => action.label)).toEqual(['Начать заново', 'Завершить'])
        expect(step(key).route?.(ctx)).toBeUndefined()
      }
    })

    it('«Начать заново» перезапускает тур и ведёт к шагу 1; «Завершить» — dismissed', async () => {
      const ctx = makeCtx({ deleted: true })
      const view = viewOf('sources.sample', ctx)
      const tour = api()
      view.actions?.[0]?.run(tour)
      await vi.waitFor(() => expect(tour.goto).toHaveBeenCalledWith('project.create'))
      expect(ctx.ops.restart).toHaveBeenCalled()
      view.actions?.[1]?.run(tour)
      expect(tour.finish).toHaveBeenCalledWith('dismissed')
    })

    it('при удалении шаги не пропускаются и не завершаются по данным', () => {
      const ctx = makeCtx({ deleted: true, runActive: true, result: result({ openQuestions: 0 }) })
      expect(step('run.start').doneWhen?.(ctx)).toBe(false)
      expect(step('question.answer').skipIf?.(ctx)).toBe(false)
    })
  })

  it('шаг 5: пропуск ведёт к шагу 10 (в ожидание несуществующего прогона не пускает)', () => {
    const skip = step('run.start').actions?.[0]
    expect(skip?.label).toBe('Пропустить главу')
    const tour = api()
    skip?.run(tour)
    expect(tour.goto).toHaveBeenCalledWith('share.create')
  })

  it('шаг 7 освобождает всю форму ответа, шаг 8 подсвечивает кнопку в другой карточке', () => {
    const ctx = makeCtx()
    const answer = step('question.answer').cardAnchor
    const ignore = step('question.ignore').cardAnchor
    expect(typeof answer === 'function' && answer(ctx)).toEqual({
      selector: '[data-question-id="q1"]',
    })
    expect(typeof ignore === 'function' && ignore(ctx)).toEqual({
      selector: '[data-question-id="q2"]',
    })
    expect(viewOf('question.answer', ctx).cardAnchor).toEqual({
      selector: '[data-question-id="q1"]',
    })
    expect(viewOf('question.answer', ctx).align).toBe('start')
    expect(viewOf('question.answer', ctx).anchor).toEqual({
      selector:
        '[data-question-id="q1"] [data-tour="answer.composer"], [data-question-id="q1"] [data-tour="question.answer"]',
    })
    const voice = makeCtx({ present: { ...ctx.present, voiceCapture: true } })
    expect(viewOf('question.answer', voice).anchor).toBe('voice.capture')
    expect(viewOf('question.answer', voice).cardAnchor).toBe('voice.capture')
  })

  it('шаги 2–4: карточка справа от кнопки, по её верхнему краю', () => {
    for (const key of ['sources.sample', 'sources.text', 'sources.voice']) {
      expect(step(key)).toMatchObject({ side: 'right', align: 'start' })
    }
  })

  it('финал: «Открыть чек-лист» завершает тур и открывает панель, «Готово» только завершает', () => {
    const ctx = makeCtx()
    const view = viewOf('finish', ctx)
    expect(view.actions?.map((action) => action.label)).toEqual(['Открыть чек-лист', 'Готово'])
    const open = api()
    view.actions?.[0]?.run(open)
    expect(open.finish).toHaveBeenCalledWith('completed')
    expect(ctx.ui.openChecklist).toHaveBeenCalled()
    const done = api()
    view.actions?.[1]?.run(done)
    expect(done.finish).toHaveBeenCalledWith('completed')
    expect(ctx.ui.openChecklist).toHaveBeenCalledTimes(1)
  })

  it('шаг 10: «Далее» закрывает окно со ссылкой', () => {
    const ctx = makeCtx({ shareCreated: true })
    const view = viewOf('share.create', ctx)
    const tour = api()
    view.actions?.[0]?.run(tour)
    expect(ctx.ui.closeShareDialog).toHaveBeenCalled()
    expect(tour.next).toHaveBeenCalled()
  })

  it('шаг 2: «Далее» листает страницу, на второй — только «Пропустить шаг»', () => {
    const ctx = makeCtx()
    expect(viewOf('sources.sample', ctx, { page: 0 }).actions?.map((a) => a.label)).toEqual([
      'Далее',
      'Пропустить шаг',
    ])
    expect(viewOf('sources.sample', ctx, { page: 1 }).actions).toBeUndefined()
  })
})

describe('сессия тура', () => {
  beforeEach(() => {
    stopTour()
    resetTourSession()
  })

  const emit = async (signal: OnboardingSignal) => {
    const { emitOnboardingSignal } = await import('@/shared/lib/onboarding-signals')
    emitOnboardingSignal(signal)
  }

  it('вне тура ничего не записывает', async () => {
    await emit({ type: 'project.created', id: 'p1' })
    expect(useTourSession.getState().projectId).toBeNull()
  })

  it('запоминает учебный проект только на шаге 1', async () => {
    startTour('sources.sample')
    await emit({ type: 'project.created', id: 'other' })
    expect(useTourSession.getState().projectId).toBeNull()
    startTour('project.create')
    await emit({ type: 'project.created', id: 'p1' })
    expect(useTourSession.getState().projectId).toBe('p1')
  })

  it('прогон: старт сбрасывает прежний итог, окончание записывает новый', async () => {
    startTour('run.wait')
    useTourSession.getState().setServerProjectId('p1')
    await emit({ type: 'run.status', status: 'queued', projectId: 'p1' })
    expect(useTourSession.getState().runStatus).toBe('queued')
    await emit({
      type: 'run.finished',
      status: 'failed',
      openQuestions: 0,
      hasDiagram: false,
      projectId: 'p1',
    })
    expect(useTourSession.getState()).toMatchObject({
      runStatus: null,
      runResult: { status: 'failed', openQuestions: 0, hasDiagram: false },
    })
    useTourSession.getState().setRetryPending(true)
    await emit({ type: 'run.started', id: 'r2', projectId: 'p1' })
    expect(useTourSession.getState()).toMatchObject({ runResult: null, retryPending: false })
  })

  it('прогон другого проекта (тур на паузе) итог учебного не затирает', async () => {
    startTour('run.wait')
    useTourSession.getState().setServerProjectId('p1')
    useTourSession
      .getState()
      .setRunResult({ status: 'succeeded', openQuestions: 2, hasDiagram: true })
    await emit({ type: 'run.started', id: 'r9', projectId: 'other' })
    await emit({
      type: 'run.finished',
      status: 'failed',
      openQuestions: 0,
      hasDiagram: false,
      projectId: 'other',
    })
    expect(useTourSession.getState().runResult).toEqual({
      status: 'succeeded',
      openQuestions: 2,
      hasDiagram: true,
    })
  })

  it('сброс не забывает учебный проект с сервера', () => {
    useTourSession.getState().setServerProjectId('p1')
    useTourSession.getState().setPickedId('q1')
    resetTourSession()
    expect(useTourSession.getState()).toMatchObject({ serverProjectId: 'p1', pickedId: null })
  })

  it('ответ и ссылка запоминаются на своих шагах', async () => {
    startTour('question.answer')
    await emit({ type: 'question.answered', id: 'q1' })
    expect(useTourSession.getState().answeredId).toBe('q1')
    startTour('share.create')
    await emit({ type: 'share.created' })
    expect(useTourSession.getState().shareCreated).toBe(true)
    resetTourSession()
    expect(useTourSession.getState().shareCreated).toBe(false)
  })
})
