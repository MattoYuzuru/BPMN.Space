import { useEffect, useState } from 'react'
import { TOUR_LAYER_ATTR } from '@/shared/lib/tour-anchors'

/** Сколько ждём появления якоря, прежде чем показать запасной вариант. */
export const ANCHOR_TIMEOUT_MS = 5000
const POLL_MS = 250

/** Окно или панель (Radix Dialog), внутри которых лежит элемент; слои обучения не считаются. */
const MODAL_SELECTOR = '[role="dialog"], [role="alertdialog"]'
const OPEN_MODALS = '[role="dialog"][data-state="open"], [role="alertdialog"][data-state="open"]'

/** Элемент найден и показан: подключён к документу и не `display: none`. */
export function isUsable(element: Element | null): element is HTMLElement {
  if (!element?.isConnected) return false
  const check = (element as HTMLElement).checkVisibility
  return typeof check === 'function' ? check.call(element) : true
}

export function findAnchor(selector: string): HTMLElement | null {
  try {
    const element = document.querySelector(selector)
    return isUsable(element) ? element : null
  } catch {
    return null
  }
}

/** Модальное окно или панель, в которой лежит якорь (карточка тура рендерится внутрь неё). */
export function modalAround(element: Element | null): HTMLElement | null {
  const modal = element?.closest<HTMLElement>(MODAL_SELECTOR) ?? null
  if (modal?.closest(`[${TOUR_LAYER_ATTR}]`)) return null
  return modal
}

/** Верхнее открытое модальное окно или панель (не слой обучения): запасной контейнер для карточки. */
export function topOpenModal(): HTMLElement | null {
  const all = [...document.querySelectorAll<HTMLElement>(OPEN_MODALS)].filter(
    (node) => !node.closest(`[${TOUR_LAYER_ATTR}]`),
  )
  return all.at(-1) ?? null
}

export interface AnchorState {
  element: HTMLElement | null
  /** Якорь не появился за таймаут. */
  timedOut: boolean
}

interface StoredAnchor extends AnchorState {
  /** Селектор, для которого получено состояние: чужое состояние на рендере не показываем. */
  selector: string | null
}

const EMPTY: AnchorState = { element: null, timedOut: false }
const EMPTY_STORED: StoredAnchor = { ...EMPTY, selector: null }

/**
 * Ждёт появления элемента: MutationObserver за документом плюс опрос раз в 250 мс, пока ждём
 * (ловит видимость, которую меняют стили). Появился — сообщает элемент и дальше следит за его
 * исчезновением (ожидание начинается заново); не появился за `timeoutMs` — флаг `timedOut`.
 * Без `selector` ничего не наблюдается.
 */
export function useAnchorElement(
  selector: string | null,
  { timeoutMs = ANCHOR_TIMEOUT_MS, enabled = true }: { timeoutMs?: number; enabled?: boolean } = {},
): AnchorState {
  const [state, setState] = useState<StoredAnchor>(EMPTY_STORED)

  useEffect(() => {
    if (!enabled || !selector) {
      setState(EMPTY_STORED)
      return
    }
    let current: HTMLElement | null = null
    let timeout = 0
    let poll = 0
    const stopWaiting = () => {
      window.clearTimeout(timeout)
      window.clearInterval(poll)
    }
    const startWaiting = () => {
      stopWaiting()
      timeout = window.setTimeout(() => {
        window.clearInterval(poll)
        // Якорь мог появиться между опросами: сначала ещё раз ищем, и только потом сдаёмся.
        const late = findAnchor(selector)
        if (late) {
          current = late
          setState({ element: late, timedOut: false, selector })
          return
        }
        setState((prev) => (prev.element ? prev : { element: null, timedOut: true, selector }))
      }, timeoutMs)
      poll = window.setInterval(check, POLL_MS)
    }
    function check() {
      const found = findAnchor(selector as string)
      if (found === current) return
      current = found
      if (found) {
        stopWaiting()
        setState({ element: found, timedOut: false, selector })
      } else {
        setState({ ...EMPTY, selector })
        startWaiting()
      }
    }

    setState({ ...EMPTY, selector })
    check()
    if (!current) startWaiting()
    // Наблюдатель не чаще раза в кадр: на тяжёлых экранах (холст схемы) мутаций много.
    let frame = 0
    const observer = new MutationObserver(() => {
      if (!frame) {
        frame = requestAnimationFrame(() => {
          frame = 0
          check()
        })
      }
    })
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['hidden', 'data-state'],
    })
    return () => {
      stopWaiting()
      if (frame) cancelAnimationFrame(frame)
      observer.disconnect()
    }
  }, [selector, timeoutMs, enabled])

  // Состояние предыдущего шага на первом рендере нового не показываем.
  if (!enabled || state.selector !== selector) return EMPTY
  return { element: state.element, timedOut: state.timedOut }
}

/**
 * Открыто ли меню, список выбора или окно поверх страницы (не слой обучения). Они лежат на z-50 под
 * затемнением тура, поэтому на время его показа тур снимает затемнение и перехват кликов.
 */
export function useFloatingLayerOpen(enabled: boolean): boolean {
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!enabled) {
      setOpen(false)
      return
    }
    let frame = 0
    const check = () => {
      frame = 0
      const layers = document.querySelectorAll(
        `[role="menu"][data-state="open"], [role="listbox"][data-state="open"], ${OPEN_MODALS}`,
      )
      setOpen([...layers].some((layer) => !layer.closest(`[${TOUR_LAYER_ATTR}]`)))
    }
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(check)
    }
    check()
    const observer = new MutationObserver(schedule)
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['data-state'],
    })
    return () => {
      if (frame) cancelAnimationFrame(frame)
      observer.disconnect()
    }
  }, [enabled])

  return open
}

/**
 * Окно перестало «выезжать». Пока у окна идёт анимация появления, оно — containing block для
 * fixed-потомков (transform), и Floating UI считает позицию карточки от него; после окончания
 * анимации позиция не пересчитывается и карточка уезжает. Поэтому карточку внутрь окна
 * показываем, только когда анимации завершились (не больше 800 мс).
 */
export function useAnimationsSettled(element: HTMLElement | null): boolean {
  const [settledFor, setSettledFor] = useState<HTMLElement | null>(null)

  useEffect(() => {
    if (!element) return
    if (typeof element.getAnimations !== 'function') {
      setSettledFor(element)
      return
    }
    let cancelled = false
    const done = () => {
      if (!cancelled) setSettledFor(element)
    }
    Promise.allSettled(element.getAnimations().map((animation) => animation.finished)).then(done)
    const timer = window.setTimeout(done, 800)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [element])

  return !element || settledFor === element
}
