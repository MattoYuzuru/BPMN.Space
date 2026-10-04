import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createTourController, nextVisibleStep, resolveView, stepCounter } from './machine'
import { startTour, stopTour, useTourStore } from './store'
import type { TourEndReason, TourStep } from './types'

interface Ctx {
  skipSecond: boolean
  skipFourth: boolean
}

const steps: TourStep<Ctx>[] = [
  {
    key: 'a',
    chapter: 'one',
    title: 'Рассказ',
    kind: 'story',
    pages: [{ text: 'a1' }, { text: 'a2' }, { text: 'a3' }],
  },
  { key: 'b', chapter: 'one', title: 'Действие', kind: 'action', pages: [{ text: 'b1' }] },
  {
    key: 'c',
    chapter: 'two',
    title: 'Второй рассказ',
    kind: 'story',
    pages: [{ text: 'c1' }, { text: 'c2' }],
    skipIf: (ctx) => ctx.skipSecond,
  },
  {
    key: 'd',
    chapter: 'two',
    title: 'Третий рассказ',
    kind: 'story',
    pages: [{ text: 'd1' }, { text: 'd2' }],
    skipIf: (ctx) => ctx.skipFourth,
  },
  { key: 'e', chapter: null, title: 'Финал', kind: 'finish', pages: [{ text: 'e1' }] },
]

function setup(ctx: Partial<Ctx> = {}) {
  const context: Ctx = { skipSecond: false, skipFourth: false, ...ctx }
  const onEnd = vi.fn<(reason: TourEndReason) => void>()
  const controller = createTourController<Ctx>({
    steps: () => steps,
    context: () => context,
    onEnd,
  })
  return { controller, onEnd, context }
}

const state = () => useTourStore.getState()

beforeEach(() => {
  stopTour()
})

describe('машина шагов', () => {
  it('рассказ листает страницы, затем уходит на следующий шаг', () => {
    const { controller } = setup()
    startTour('a')
    controller.next()
    expect(state()).toMatchObject({ stepKey: 'a', page: 1 })
    controller.next()
    expect(state()).toMatchObject({ stepKey: 'a', page: 2 })
    controller.next()
    expect(state()).toMatchObject({ stepKey: 'b', page: 0 })
    expect(state().history).toEqual(['a'])
  })

  it('пропускает шаги по skipIf при переходе', () => {
    const { controller } = setup({ skipSecond: true })
    startTour('b')
    controller.skipStep()
    expect(state().stepKey).toBe('d')
    expect(state().history).toEqual(['b'])
  })

  it('пропускает шаг по skipIf и при прямом переходе goto', () => {
    const { controller } = setup({ skipSecond: true })
    startTour('a')
    controller.goto('c')
    expect(state().stepKey).toBe('d')
  })

  it('если дальше все шаги пропущены, тур завершается как пройденный', () => {
    const { controller, onEnd } = setup({ skipSecond: true, skipFourth: true })
    startTour('b')
    controller.skipStep()
    expect(state().stepKey).toBe('e')
    controller.finish('completed')
    expect(state().status).toBe('idle')
    expect(onEnd).toHaveBeenCalledWith('completed')
  })

  it('завершается после последнего шага', () => {
    const { controller, onEnd } = setup()
    startTour('e')
    controller.next()
    expect(state().status).toBe('idle')
    expect(onEnd).toHaveBeenCalledWith('completed')
  })

  it('«Назад» работает только у рассказов', () => {
    const { controller } = setup()
    startTour('a')
    expect(controller.canBack()).toBe(false)
    controller.next()
    expect(controller.canBack()).toBe(true)
    controller.back()
    expect(state()).toMatchObject({ stepKey: 'a', page: 0 })
    controller.skipStep()
    // шаг-действие: «Назад» нет, даже если до него был рассказ
    expect(state().stepKey).toBe('b')
    expect(controller.canBack()).toBe(false)
    controller.back()
    expect(state().stepKey).toBe('b')
  })

  it('на первой странице рассказа «Назад» нет, если до него было действие', () => {
    const { controller } = setup()
    startTour('b')
    controller.skipStep()
    expect(state().stepKey).toBe('c')
    expect(controller.canBack()).toBe(false)
  })

  it('«Назад» между рассказами встаёт на последнюю страницу предыдущего', () => {
    const { controller } = setup()
    startTour('b')
    controller.skipStep()
    controller.next()
    controller.next()
    expect(state()).toMatchObject({ stepKey: 'd', page: 0, history: ['b', 'c'] })
    expect(controller.canBack()).toBe(true)
    controller.back()
    expect(state()).toMatchObject({ stepKey: 'c', page: 1, history: ['b'] })
  })

  it('goto переходит по ключу и запоминает историю (ветвления)', () => {
    const { controller } = setup()
    startTour('b')
    controller.goto('e')
    expect(state()).toMatchObject({ stepKey: 'e', history: ['b'] })
    controller.goto('нет-такого')
    expect(state().stepKey).toBe('e')
  })

  it('подтверждение завершения: запрос, отмена, подтверждение', () => {
    const { controller, onEnd } = setup()
    startTour('a')
    controller.requestEnd()
    expect(state().confirming).toBe(true)
    controller.cancelEnd()
    expect(state().confirming).toBe(false)
    controller.finish('dismissed')
    expect(onEnd).toHaveBeenCalledWith('dismissed')
    expect(state().status).toBe('idle')
  })

  it('вход в шаг сбрасывает страницу, сигналы и подтверждение', () => {
    const { controller } = setup()
    startTour('a')
    state().recordSignal({ type: 'share.created' })
    controller.requestEnd()
    controller.skipStep()
    expect(state()).toMatchObject({ stepKey: 'b', page: 0, confirming: false, seen: {} })
  })

  it('отмечает прочитанные страницы', () => {
    const { controller } = setup()
    startTour('a')
    controller.next()
    expect(state().readPages).toEqual({ 'a:0': true })
  })
})

describe('счётчик и видимые шаги', () => {
  it('считает номер среди непропущенных шагов', () => {
    const ctx: Ctx = { skipSecond: true, skipFourth: false }
    expect(stepCounter(steps, 'd', ctx)).toEqual({ index: 3, total: 4 })
    expect(stepCounter(steps, 'e', ctx)).toEqual({ index: 4, total: 4 })
  })

  it('nextVisibleStep возвращает undefined в конце', () => {
    const ctx: Ctx = { skipSecond: false, skipFourth: false }
    expect(nextVisibleStep(steps, 4, ctx)).toBeUndefined()
    expect(nextVisibleStep(steps, 0, ctx)?.key).toBe('b')
  })
})

describe('resolveView', () => {
  const base = { ctx: { skipSecond: false, skipFourth: false }, elapsedMs: 0, seen: {}, page: 0 }

  it('страница перекрывает view, view перекрывает шаг', () => {
    const step: TourStep<Ctx> = {
      key: 'x',
      chapter: null,
      title: 'Шаг',
      kind: 'story',
      anchor: 'step.anchor',
      pages: [{ text: 'p1' }, { text: 'p2', anchor: 'page.anchor', allowOutside: true }],
      view: ({ elapsedMs }) =>
        elapsedMs > 1000 ? { title: 'Долго', tone: 'waiting', anchor: 'view.anchor' } : undefined,
    }
    expect(resolveView(step, base)).toMatchObject({
      title: 'Шаг',
      text: 'p1',
      anchor: 'step.anchor',
      allowOutside: false,
      tone: 'default',
    })
    expect(resolveView(step, { ...base, elapsedMs: 2000 })).toMatchObject({
      title: 'Долго',
      tone: 'waiting',
      anchor: 'view.anchor',
    })
    expect(resolveView(step, { ...base, elapsedMs: 2000, page: 1 })).toMatchObject({
      text: 'p2',
      anchor: 'page.anchor',
      allowOutside: true,
    })
  })

  it('якорь может зависеть от контекста; null — по центру', () => {
    const step: TourStep<Ctx> = {
      key: 'x',
      chapter: null,
      title: 'Шаг',
      kind: 'action',
      anchor: (ctx) => (ctx.skipSecond ? 'one' : undefined),
      pages: [{ text: 'p' }, { text: 'q', anchor: null }],
    }
    expect(resolveView(step, base).anchor).toBeNull()
    expect(
      resolveView(step, { ...base, ctx: { skipSecond: true, skipFourth: false } }).anchor,
    ).toBe('one')
    expect(resolveView(step, { ...base, page: 1 }).anchor).toBeNull()
  })
})
