import { useEffect, useState } from 'react'

/** Прямоугольник в координатах окна (как getBoundingClientRect). */
export interface Rect {
  x: number
  y: number
  width: number
  height: number
}

export function rectOf(element: Element): Rect {
  const { x, y, width, height } = element.getBoundingClientRect()
  return { x, y, width, height }
}

/** Rect как DOMRect — для виртуальных якорей Radix Popper (в jsdom конструктора DOMRect нет). */
export function toDomRect(rect: Rect): DOMRect {
  return {
    ...rect,
    top: rect.y,
    left: rect.x,
    right: rect.x + rect.width,
    bottom: rect.y + rect.height,
    toJSON: () => rect,
  } as DOMRect
}

export function sameRect(a: Rect | null, b: Rect | null): boolean {
  if (a === b) return true
  if (!a || !b) return false
  return a.x === b.x && a.y === b.y && a.width === b.width && a.height === b.height
}

/**
 * Следит за положением элемента: ResizeObserver, прокрутка любого предка и ресайз окна
 * (capture), троттлинг через requestAnimationFrame. `settleMs` — первые мс после появления
 * элемента кадры снимаются непрерывно (окно ещё «выезжает» анимацией, ResizeObserver молчит).
 * Без элемента ничего не наблюдается.
 */
export function useElementRect(
  element: Element | null,
  { settleMs = 450 }: { settleMs?: number } = {},
): Rect | null {
  const [rect, setRect] = useState<Rect | null>(null)

  useEffect(() => {
    if (!element) {
      setRect(null)
      return
    }
    let frame = 0
    const settleUntil = performance.now() + settleMs
    const measure = () => {
      frame = 0
      const next = rectOf(element)
      setRect((prev) => (sameRect(prev, next) ? prev : next))
      if (performance.now() < settleUntil) schedule()
    }
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(measure)
    }
    const onChange = () => schedule()
    setRect(rectOf(element))
    schedule()
    const observer = new ResizeObserver(onChange)
    observer.observe(element)
    window.addEventListener('scroll', onChange, { capture: true, passive: true })
    window.addEventListener('resize', onChange)
    return () => {
      if (frame) cancelAnimationFrame(frame)
      observer.disconnect()
      window.removeEventListener('scroll', onChange, { capture: true })
      window.removeEventListener('resize', onChange)
    }
  }, [element, settleMs])

  return rect
}
