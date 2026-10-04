import type { AnchorRef } from '@/shared/lib/tour-anchors'
import { useTourStore } from './store'
import type {
  CoachPage,
  SignalMemory,
  StepAction,
  StepViewContext,
  TourAlign,
  TourApi,
  TourEndReason,
  TourSide,
  TourStep,
} from './types'

/** Итоговый вид текущей страницы шага: статика шага, перекрытая `view` и страницей. */
export interface ResolvedView {
  title: string
  pages: CoachPage[]
  pageIndex: number
  text: string
  tone: 'default' | 'waiting' | 'error'
  actions: StepAction[] | undefined
  /** Ссылка на якорь; null — по центру экрана без выреза. */
  anchor: AnchorRef | null
  side: TourSide
  align: TourAlign
  /** Опора карточки; null — карточка стоит у якоря (выреза). */
  cardAnchor: AnchorRef | null
  allowOutside: boolean
}

/** Собирает вид шага. Приоритет якоря: страница, затем `view`, затем шаг. */
export function resolveView<Ctx>(step: TourStep<Ctx>, view: StepViewContext<Ctx>): ResolvedView {
  const dynamic = step.view?.(view) ?? {}
  const pages = dynamic.pages ?? step.pages
  const pageIndex = Math.max(0, Math.min(view.page, pages.length - 1))
  const page = pages[pageIndex] ?? { text: '' }
  const stepAnchor = typeof step.anchor === 'function' ? step.anchor(view.ctx) : step.anchor
  const anchor =
    page.anchor !== undefined
      ? page.anchor
      : dynamic.anchor !== undefined
        ? dynamic.anchor
        : (stepAnchor ?? null)
  return {
    title: page.title ?? dynamic.title ?? step.title,
    pages,
    pageIndex,
    text: page.text,
    tone: dynamic.tone ?? 'default',
    actions: dynamic.actions ?? step.actions,
    anchor,
    side: page.side ?? dynamic.side ?? step.side ?? 'bottom',
    align: page.align ?? dynamic.align ?? step.align ?? 'center',
    cardAnchor:
      page.cardAnchor !== undefined
        ? page.cardAnchor
        : dynamic.cardAnchor !== undefined
          ? dynamic.cardAnchor
          : ((typeof step.cardAnchor === 'function'
              ? step.cardAnchor(view.ctx)
              : step.cardAnchor) ?? null),
    allowOutside: page.allowOutside ?? dynamic.allowOutside ?? step.allowOutside ?? false,
  }
}

/** Следующий не пропущенный (`skipIf`) шаг после шага с индексом `index`. */
export function nextVisibleStep<Ctx>(
  steps: readonly TourStep<Ctx>[],
  index: number,
  ctx: Ctx,
): TourStep<Ctx> | undefined {
  for (let i = index + 1; i < steps.length; i += 1) {
    const step = steps[i]
    if (step && !step.skipIf?.(ctx)) return step
  }
  return undefined
}

/** Номер шага среди непропущенных и их число: «Шаг N из M». */
export function stepCounter<Ctx>(
  steps: readonly TourStep<Ctx>[],
  key: string,
  ctx: Ctx,
): { index: number; total: number } {
  const visible = steps.filter((step) => step.key === key || !step.skipIf?.(ctx))
  return {
    index:
      Math.max(
        0,
        visible.findIndex((step) => step.key === key),
      ) + 1,
    total: visible.length,
  }
}

export interface ControllerDeps<Ctx> {
  steps: () => readonly TourStep<Ctx>[]
  context: () => Ctx
  onEnd?: (reason: TourEndReason) => void
  store?: typeof useTourStore
}

export interface TourController extends TourApi {
  /** Показана ли «Назад» на текущем шаге и странице. */
  canBack: () => boolean
  requestEnd: () => void
  cancelEnd: () => void
}

/**
 * Машина шагов тура: переходы по страницам и шагам, пропуск по `skipIf`, «Назад» только у рассказов,
 * ветвления через `goto`, завершение. Сама ничего не рисует и не знает про сервер.
 */
export function createTourController<Ctx>(deps: ControllerDeps<Ctx>): TourController {
  const store = deps.store ?? useTourStore
  const state = () => store.getState()
  const find = (key: string | null) => deps.steps().find((step) => step.key === key)
  const indexOf = (key: string) => deps.steps().findIndex((step) => step.key === key)

  const viewOf = (step: TourStep<Ctx>, page = state().page) => {
    const { enteredAt, seen } = state()
    return resolveView(step, {
      ctx: deps.context(),
      elapsedMs: Date.now() - enteredAt,
      seen: seen as SignalMemory,
      page,
    })
  }

  const finish = (reason: TourEndReason = 'completed') => {
    if (state().status !== 'active') return
    state().stop()
    deps.onEnd?.(reason)
  }

  /** Войти в шаг; если он пропускается по `skipIf` — сразу к следующему видимому. */
  const go = (key: string, history: string[]) => {
    const step = find(key)
    if (!step) return
    if (step.kind !== 'finish' && step.skipIf?.(deps.context())) {
      const next = nextVisibleStep(deps.steps(), indexOf(key), deps.context())
      if (next) go(next.key, history)
      else finish('completed')
      return
    }
    state().enter(key, history)
  }

  const advance = () => {
    const { stepKey, history } = state()
    if (!stepKey) return
    const next = nextVisibleStep(deps.steps(), indexOf(stepKey), deps.context())
    if (!next) finish('completed')
    else go(next.key, [...history, stepKey])
  }

  const previousStory = () => {
    const key = state().history.at(-1)
    const step = find(key ?? null)
    return step?.kind === 'story' ? step : undefined
  }

  const canBack = () => {
    const step = find(state().stepKey)
    if (step?.kind !== 'story') return false
    return state().page > 0 || previousStory() !== undefined
  }

  return {
    next: () => {
      const { stepKey, page } = state()
      const step = find(stepKey)
      if (!stepKey || !step) return
      state().markRead(stepKey, page)
      if (page < viewOf(step).pages.length - 1) state().setPage(page + 1)
      else advance()
    },
    back: () => {
      if (!canBack()) return
      const { page, history } = state()
      if (page > 0) {
        state().setPage(page - 1)
        return
      }
      const previous = previousStory()
      if (!previous) return
      state().enter(previous.key, history.slice(0, -1))
      state().setPage(viewOf(previous, 0).pages.length - 1)
    },
    skipStep: advance,
    goto: (key) => {
      const { stepKey, history } = state()
      if (!stepKey || !find(key)) return
      go(key, [...history, stepKey])
    },
    finish,
    canBack,
    requestEnd: () => state().setConfirming(true),
    cancelEnd: () => state().setConfirming(false),
  }
}
