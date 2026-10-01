import { type CSSProperties, type RefObject, useLayoutEffect, useState } from 'react'

interface Box {
  left: number
  top: number
  width: number
  height: number
}

/**
 * Следит за активным элементом внутри контейнера и возвращает стиль для «бегунка»,
 * который мягко переезжает между вкладками/сегментами. Первая отрисовка — без анимации.
 */
export function useActiveIndicator(
  containerRef: RefObject<HTMLElement | null>,
  activeSelector: string,
): { style: CSSProperties; visible: boolean } {
  const [box, setBox] = useState<Box | null>(null)
  const [animated, setAnimated] = useState(false)

  useLayoutEffect(() => {
    const container = containerRef.current
    if (!container) return
    let frame = 0
    const measure = () => {
      const active = container.querySelector<HTMLElement>(activeSelector)
      setBox(
        active
          ? {
              left: active.offsetLeft,
              top: active.offsetTop,
              width: active.offsetWidth,
              height: active.offsetHeight,
            }
          : null,
      )
    }
    measure()
    // Включаем переходы только после первого кадра, чтобы бегунок не «прилетал» при монтировании.
    frame = requestAnimationFrame(() => setAnimated(true))
    const mutations = new MutationObserver(measure)
    mutations.observe(container, {
      attributes: true,
      subtree: true,
      attributeFilter: ['data-state'],
    })
    const resize = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure)
    resize?.observe(container)
    for (const child of Array.from(container.children)) resize?.observe(child)
    void document.fonts?.ready.then(measure)
    return () => {
      cancelAnimationFrame(frame)
      mutations.disconnect()
      resize?.disconnect()
    }
  }, [containerRef, activeSelector])

  return {
    visible: box !== null,
    style: box
      ? {
          width: box.width,
          height: box.height,
          transform: `translate3d(${box.left}px, ${box.top}px, 0)`,
          transitionDuration: animated ? undefined : '0ms',
        }
      : {},
  }
}
