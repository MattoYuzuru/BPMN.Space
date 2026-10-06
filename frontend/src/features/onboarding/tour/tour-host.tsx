import { useRouter } from '@tanstack/react-router'
import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { type Rect, toDomRect, useElementRect } from '@/shared/hooks/use-element-rect'
import { cn } from '@/shared/lib/cn'
import { subscribeOnboardingSignals } from '@/shared/lib/onboarding-signals'
import { anchorSelector, TOUR_LAYER_ATTR } from '@/shared/lib/tour-anchors'
import { Button, type CoachAction, CoachCard, Spotlight } from '@/shared/ui'
import {
  ANCHOR_TIMEOUT_MS,
  modalAround,
  topOpenModal,
  useAnchorElement,
  useAnimationsSettled,
  useFloatingLayerOpen,
} from '../anchor'
import { createTourController, nextVisibleStep, resolveView, stepCounter } from './machine'
import { persistQuietly } from './persistence'
import { startTour, stopTour, useTourStore } from './store'
import type { RouteTarget, StepAction, TourEndReason, TourPersistence, TourStep } from './types'

export interface TourHostProps<Ctx> {
  steps: readonly TourStep<Ctx>[]
  /** Контекст приложения для шагов (id учебного проекта, вопросы, прогон). Обновляйте по мере изменений. */
  context: Ctx
  persistence: TourPersistence
  /** Подписи глав: ключ главы шага → «Источники». */
  chapters?: Record<string, string>
  /** Сколько ждать якорь до запасной карточки по центру, мс (по умолчанию 5000). */
  anchorTimeoutMs?: number
  /** Тур закончился: пройден или завершён пользователем. Сервер уже уведомлён через `persistence`. */
  onEnd?: (reason: TourEndReason) => void
  /** При монтировании восстановить шаг из `persistence.load()`, если тур на сервере активен. */
  restore?: boolean
}

/** Минимум роутера, который нужен туру; без роутера (тесты, витрина) тур к маршрутам не привязан. */
interface RouterLike {
  navigate: (options: unknown) => Promise<unknown> | undefined
  matchRoute: (location: unknown, options?: unknown) => unknown
  subscribe: (event: string, listener: () => void) => () => void
}

function routeMatches(router: RouterLike, target: RouteTarget): boolean {
  return [{ to: target.to, params: target.params }, ...(target.alt ?? [])].some(
    (location) => router.matchRoute(location, { fuzzy: false }) !== false,
  )
}

/** В окне уже печатают (фокус в поле ввода): карточка не отбирает у человека фокус. */
function typingInside(modal: HTMLElement | null): boolean {
  const active = document.activeElement
  return Boolean(
    modal &&
      active instanceof HTMLElement &&
      modal.contains(active) &&
      active.matches('input, textarea, [contenteditable="true"]'),
  )
}

/** Пилюля паузы: пользователь ушёл с экрана шага. */
function PausePill({ onResume, onEnd }: { onResume: () => void; onEnd: () => void }) {
  const [confirming, setConfirming] = useState(false)
  const pill = (
    <section
      {...{ [TOUR_LAYER_ATTR]: '' }}
      aria-label="Обучение приостановлено"
      className="pointer-events-auto fixed bottom-6 left-1/2 z-70 flex -translate-x-1/2 items-center gap-2 rounded-lg border border-border bg-surface-raised p-2 pl-4 shadow-lg animate-pop-in"
    >
      {confirming ? (
        <>
          <span className="type-ui text-fg">Завершить обучение?</span>
          <Button variant="ghost" size="sm" onClick={() => setConfirming(false)}>
            Продолжить обучение
          </Button>
          <Button variant="primary" tone="danger" size="sm" onClick={onEnd}>
            Завершить
          </Button>
        </>
      ) : (
        <>
          <span className="type-ui text-fg-muted">Обучение приостановлено</span>
          <Button variant="primary" size="sm" onClick={onResume}>
            Вернуться к обучению
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setConfirming(true)}>
            Завершить
          </Button>
        </>
      )}
    </section>
  )
  return createPortal(pill, document.body)
}

/**
 * Хост тура: машина шагов, ожидание якоря, переходы между экранами, пауза, сохранение шага,
 * затемнение с вырезом и карточка. Грузится отдельным чанком (`TourHost` из `./index`).
 *
 * Если якорь лежит внутри модального окна или панели, затемнение не рисуется (у окна своё),
 * кольцо остаётся, а карточка выводится внутрь узла окна — так она внутри FocusScope Radix и
 * не считается «кликом снаружи».
 */
export default function TourHost<Ctx>({
  steps,
  context,
  persistence,
  chapters = {},
  anchorTimeoutMs = ANCHOR_TIMEOUT_MS,
  onEnd,
  restore = true,
}: TourHostProps<Ctx>) {
  const router = useRouter({ warn: false }) as unknown as RouterLike | undefined
  const status = useTourStore((s) => s.status)
  const stepKey = useTourStore((s) => s.stepKey)
  const page = useTourStore((s) => s.page)
  const paused = useTourStore((s) => s.paused)
  const confirming = useTourStore((s) => s.confirming)
  const attention = useTourStore((s) => s.attention)
  const seen = useTourStore((s) => s.seen)
  const enteredAt = useTourStore((s) => s.enteredAt)
  const readPages = useTourStore((s) => s.readPages)
  const active = status === 'active'

  const stepsRef = useRef(steps)
  stepsRef.current = steps
  const contextRef = useRef(context)
  contextRef.current = context
  const persistenceRef = useRef(persistence)
  persistenceRef.current = persistence
  const onEndRef = useRef(onEnd)
  onEndRef.current = onEnd

  const controller = useMemo(
    () =>
      createTourController<Ctx>({
        steps: () => stepsRef.current,
        context: () => contextRef.current,
        onEnd: (reason) => {
          persistQuietly(() => persistenceRef.current.setStatus(reason))
          onEndRef.current?.(reason)
        },
      }),
    [],
  )

  const step = active ? steps.find((item) => item.key === stepKey) : undefined
  const [, setTick] = useState(0)
  const [locationTick, setLocationTick] = useState(0)
  // Навигации, запущенные самим туром и ещё не завершённые (их может быть несколько подряд).
  const pendingNavigations = useRef(0)

  // Неизвестный ключ шага (опечатка в startTour): тур не показываем и останавливаем.
  const unknownStep = active && stepKey !== null && !steps.some((item) => item.key === stepKey)
  useEffect(() => {
    if (unknownStep) stopTour()
  }, [unknownStep])

  // Восстановление шага с сервера при загрузке любой вкладки приложения.
  useEffect(() => {
    if (!restore || useTourStore.getState().status === 'active') return
    let cancelled = false
    persistenceRef.current
      .load()
      .then(({ status: remote, step: key }) => {
        if (cancelled || useTourStore.getState().status === 'active') return
        if (remote === 'active' && key && stepsRef.current.some((item) => item.key === key)) {
          startTour(key, { restored: true })
        }
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [restore])

  // Начало тура и вход в шаг — в фоне на сервер (восстановленный шаг повторно не пишем).
  useEffect(() => {
    if (active && !useTourStore.getState().restored) {
      persistQuietly(() => persistenceRef.current.setStatus('active'))
    }
  }, [active])
  useEffect(() => {
    if (!active || !stepKey || useTourStore.getState().restored) return
    persistQuietly(() => persistenceRef.current.saveStep(stepKey))
  }, [active, stepKey])

  // Сигналы приложения: запоминаем и завершаем шаги-действия по `until`.
  useEffect(() => {
    if (!active) return
    return subscribeOnboardingSignals((signal) => {
      const store = useTourStore.getState()
      store.recordSignal(signal)
      // Пока тур на паузе, пользователя в другой экран не утаскиваем.
      if (store.paused) return
      const current = stepsRef.current.find((item) => item.key === store.stepKey)
      if (!current || (current.kind !== 'action' && current.kind !== 'wait')) return
      if (current.until?.(signal, contextRef.current)) controller.skipStep()
    })
  }, [active, controller])

  // Условия по состоянию приложения: `doneWhen` и `skipIf` проверяются после каждого обновления.
  useEffect(() => {
    if (!step || paused) return
    if ((step.kind === 'action' || step.kind === 'wait') && step.doneWhen?.(context)) {
      controller.skipStep()
    } else if (step.kind !== 'finish' && step.skipIf?.(context)) {
      controller.skipStep()
    }
  })

  // Подготовка экрана при входе в шаг (развернуть панель) и её откат при выходе.
  useEffect(() => {
    if (!active || !stepKey) return
    const current = stepsRef.current.find((item) => item.key === stepKey)
    return current?.prepare?.(contextRef.current)
  }, [active, stepKey])

  // Моменты пересчёта `view` по времени (таймауты ожидания прогона).
  useEffect(() => {
    if (!active || !stepKey) return
    const current = stepsRef.current.find((item) => item.key === stepKey)
    const start = enteredAt
    const timers = (current?.ticks ?? []).map((at) =>
      window.setTimeout(() => setTick((n) => n + 1), Math.max(0, at - (Date.now() - start))),
    )
    return () => {
      for (const timer of timers) window.clearTimeout(timer)
    }
  }, [active, stepKey, enteredAt])

  // Маршрутизация: переход на экран шага, пауза при уходе, возврат.
  useEffect(() => {
    if (!router) return
    return router.subscribe('onResolved', () => setLocationTick((n) => n + 1))
  }, [router])

  // Экран шага может появиться позже (id проекта приходит после создания): цель — в зависимостях.
  const routeKey = step ? JSON.stringify(step.route?.(context) ?? null) : null
  // biome-ignore lint/correctness/useExhaustiveDependencies: переход — при входе в шаг, снятии паузы и смене цели
  useEffect(() => {
    if (!active || paused || !router || !stepKey) return
    const current = stepsRef.current.find((item) => item.key === stepKey)
    const target = current?.route?.(contextRef.current)
    if (!target || routeMatches(router, target)) return
    pendingNavigations.current += 1
    Promise.resolve(
      router.navigate({ to: target.to, params: target.params, search: target.search }),
    )
      .catch(() => {})
      .finally(() => {
        pendingNavigations.current -= 1
        setLocationTick((n) => n + 1)
      })
  }, [active, paused, stepKey, routeKey])

  // biome-ignore lint/correctness/useExhaustiveDependencies: locationTick и context — триггеры перепроверки маршрута
  useEffect(() => {
    if (!active || !router || !stepKey) return
    const onRoute = () => {
      const current = stepsRef.current.find((item) => item.key === useTourStore.getState().stepKey)
      const target = current?.route?.(contextRef.current)
      return !target || routeMatches(router, target)
    }
    if (onRoute()) {
      if (paused) useTourStore.getState().setPaused(false)
      return
    }
    if (paused || pendingNavigations.current > 0) return
    // Пауза с задержкой: действие шага может само сменить экран и тут же продвинуть тур по сигналу.
    const timer = window.setTimeout(() => {
      if (!onRoute() && pendingNavigations.current === 0) useTourStore.getState().setPaused(true)
    }, 250)
    return () => window.clearTimeout(timer)
  }, [active, paused, stepKey, locationTick, router, context])

  // Вид шага и ожидание якоря.
  const view = step
    ? resolveView(step, { ctx: context, elapsedMs: Date.now() - enteredAt, seen, page })
    : null
  const selector = view?.anchor ? anchorSelector(view.anchor) : null
  const anchor = useAnchorElement(selector, {
    timeoutMs: anchorTimeoutMs,
    enabled: active && !paused,
  })
  const rect = useElementRect(anchor.element)
  // Опора карточки отдельно от выреза: карточка стоит у неё, а подсвечена кнопка внутри.
  const cardSelector = view?.cardAnchor ? anchorSelector(view.cardAnchor) : null
  const cardAnchor = useAnchorElement(cardSelector, {
    timeoutMs: anchorTimeoutMs,
    enabled: active && !paused,
  })
  const cardRect = useElementRect(cardAnchor.element)
  const cardRectRef = useRef<Rect | null>(null)
  cardRectRef.current = cardAnchor.element ? cardRect : null
  const floating = useFloatingLayerOpen(active && !paused)
  // Окно, в котором лежит якорь, а если якоря нет или он вне окна — верхнее открытое окно:
  // иначе затемнение и карточка оказались бы поверх него, вне FocusScope и под aria-hidden.
  const modal = modalAround(anchor.element) ?? (floating ? topOpenModal() : null)
  const modalSettled = useAnimationsSettled(modal)
  const waiting = Boolean(selector) && (!anchor.element || !rect) && !anchor.timedOut
  const showCard = (!waiting && modalSettled) || confirming
  const focusKey = step && view ? `${step.key}:${view.pageIndex}:${confirming}` : null
  const focusedPage = useRef<string | null>(null)
  const autoFocusCard = focusedPage.current !== focusKey && !typingInside(modal)
  // Перепорталивание в только что открытый поповер не должно отбирать фокус у его контролов.
  // Фокус просим один раз при показе страницы или явном переходе в подтверждение завершения.

  // Необязательный шаг без якоря молча пропускается.
  useEffect(() => {
    if (step?.optional && step.kind !== 'finish' && anchor.timedOut) controller.skipStep()
  }, [step, anchor.timedOut, controller])

  useEffect(() => {
    anchor.element?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
  }, [anchor.element])

  // Прямоугольник для карточки: едет вместе с (анимированным) вырезом.
  const frameRef = useRef<Rect | null>(null)
  const lastTarget = useRef<Rect | null>(null)
  const virtualRef = useRef({
    getBoundingClientRect: () =>
      toDomRect(
        cardRectRef.current ??
          frameRef.current ??
          lastTarget.current ?? {
            x: window.innerWidth / 2,
            y: window.innerHeight / 2,
            width: 0,
            height: 0,
          },
      ),
  })
  if (rect) lastTarget.current = rect

  // Затухание затемнения после окончания тура.
  const [leaving, setLeaving] = useState(false)
  const wasActive = useRef(false)
  useEffect(() => {
    if (active) {
      wasActive.current = true
      setLeaving(false)
      return
    }
    if (!wasActive.current) return
    wasActive.current = false
    setLeaving(true)
    const timer = window.setTimeout(() => setLeaving(false), 260)
    return () => window.clearTimeout(timer)
  }, [active])

  if (leaving && !active) {
    return (
      <Spotlight
        target={null}
        block={false}
        className="opacity-0 transition-opacity duration-base ease-soft"
      />
    )
  }
  if (!active || !step || !view || unknownStep) return null

  if (paused) {
    return (
      <PausePill
        onResume={() => useTourStore.getState().setPaused(false)}
        onEnd={() => controller.finish('dismissed')}
      />
    )
  }

  const cutout = Boolean(anchor.element && rect)
  const dim = !modal && !floating
  // Шаг-действие без найденного якоря не должен запирать экран: действие нужно сделать.
  const stuckAction = anchor.timedOut && (step.kind === 'action' || step.kind === 'wait')
  const block = dim && !view.allowOutside && !stuckAction
  const centered = !cutout

  const counter = stepCounter(steps, step.key, context)
  const chapter = step.chapter ? (chapters[step.chapter] ?? step.chapter) : null
  const eyebrow = [chapter, `Шаг ${counter.index} из ${counter.total}`]
    .filter(Boolean)
    .join(' \u00b7 ')

  const isLastStep = nextVisibleStep(steps, steps.indexOf(step), context) === undefined
  const isLastPage = view.pageIndex >= view.pages.length - 1
  const defaults: StepAction[] =
    step.kind === 'story'
      ? [
          {
            id: 'next',
            label: isLastStep && isLastPage ? 'Готово' : 'Далее',
            variant: 'primary',
            run: (api) => api.next(),
          },
        ]
      : step.kind === 'action'
        ? [{ id: 'skip', label: 'Пропустить шаг', variant: 'ghost', run: (api) => api.skipStep() }]
        : step.kind === 'finish'
          ? [
              {
                id: 'done',
                label: 'Готово',
                variant: 'primary',
                run: (api) => api.finish('completed'),
              },
            ]
          : []
  const actions: CoachAction[] = (view.actions ?? defaults).map((action) => ({
    id: action.id,
    label: action.label,
    variant: action.variant,
    tone: action.tone,
    onClick: () => action.run(controller),
  }))
  const canBack = controller.canBack()

  return (
    <>
      <Spotlight
        target={cutout ? rect : waiting ? lastTarget.current : null}
        dim={dim}
        block={block && !waiting}
        blockAll={dim && waiting}
        transitionKey={step.key}
        onBlockedClick={() => useTourStore.getState().bumpAttention()}
        onFrame={(frame) => {
          frameRef.current = frame
        }}
        className={cn(
          'animate-fade-in',
          // Ожидание якоря: затемнение держим, но без вырезов и подсветки.
          waiting && 'cursor-progress',
        )}
      />
      {showCard && (
        <CoachCard
          placement={centered ? 'center' : 'anchor'}
          anchorRef={virtualRef}
          side={view.side}
          align={view.align}
          portalContainer={modal}
          autoFocus={autoFocusCard}
          onShown={() => {
            focusedPage.current = focusKey
          }}
          eyebrow={eyebrow}
          title={view.title}
          text={view.text}
          pageKey={`${step.key}:${view.pageIndex}`}
          textRead={Boolean(readPages[`${step.key}:${view.pageIndex}`])}
          pageCount={view.pages.length}
          pageIndex={view.pageIndex}
          tone={view.tone}
          actions={actions}
          onBack={canBack ? controller.back : undefined}
          onNext={step.kind === 'story' ? controller.next : undefined}
          attention={attention}
          confirming={confirming}
          onRequestEnd={controller.requestEnd}
          onConfirmEnd={() => controller.finish('dismissed')}
          onCancelEnd={controller.cancelEnd}
        />
      )}
    </>
  )
}
