import { useEffect, useState } from 'react'
import { TOUR_LAYER_ATTR } from '@/shared/lib/tour-anchors'

/** Сколько ждём появления якоря, прежде чем показать запасной вариант. */
export const ANCHOR_TIMEOUT_MS = 5000
const POLL_MS = 250

/** Окно или панель (Radix Dialog), внутри которых лежит элемент; слои обучения не считаются. */
const MODAL_SELECTOR = '[role="dialog"], [role="alertdialog"]'

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

export interface AnchorState {
  element: HTMLElement | null
  /** Якорь не появился за таймаут. */
  timedOut: boolean
}

const EMPTY: AnchorState = { element: null, timedOut: false }

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
  const [state, setState] = useState<AnchorState>(EMPTY)

  useEffect(() => {
    if (!enabled || !selector) {
      setState(EMPTY)
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
        setState((prev) => (prev.element ? prev : { element: null, timedOut: true }))
      }, timeoutMs)
      poll = window.setInterval(check, POLL_MS)
    }
    function check() {
      const found = findAnchor(selector as string)
      if (found === current) return
      current = found
      if (found) {
        stopWaiting()
        setState({ element: found, timedOut: false })
      } else {
        setState(EMPTY)
        startWaiting()
      }
    }

    setState(EMPTY)
    check()
    if (!current) startWaiting()
    const observer = new MutationObserver(check)
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['hidden', 'data-state'],
    })
    return () => {
      stopWaiting()
      observer.disconnect()
    }
  }, [selector, timeoutMs, enabled])

  return state
}

/**
 * Открыто ли меню или список выбора поверх страницы (не слой обучения). Меню лежит на z-50 под
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
        '[role="menu"][data-state="open"], [role="listbox"][data-state="open"]',
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
