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
 * Следит за геометрией активного якоря каждый кадр. ResizeObserver не замечает смещение
 * без изменения размера: например, центрированный диалог переезжает после исчезновения
 * подсказки или появления расшифровки. React обновляется только при изменении координат.
 * Без элемента и после снятия подсказки кадры не запрашиваются.
 */
export function useElementRect(element: Element | null): Rect | null {
  const [rect, setRect] = useState<Rect | null>(null)

  useEffect(() => {
    if (!element) {
      setRect(null)
      return
    }
    let frame = 0
    const measure = () => {
      const next = rectOf(element)
      setRect((prev) => (sameRect(prev, next) ? prev : next))
      frame = requestAnimationFrame(measure)
    }
    setRect(rectOf(element))
    frame = requestAnimationFrame(measure)
    return () => {
      cancelAnimationFrame(frame)
    }
  }, [element])

  return rect
}
