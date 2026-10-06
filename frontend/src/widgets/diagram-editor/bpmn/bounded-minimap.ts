import type Canvas from 'diagram-js/lib/core/Canvas'
import { clampNavigation, paddedBounds, projectViewport } from '../model/minimap'
import { type Box, zoomViewbox } from '../model/viewbox'

/** Адаптер установленной diagram-js-minimap@5: рисунок остаётся у библиотеки, навигация у нас. */
interface Minimap {
  _update(): void
  _svg: SVGSVGElement
  _parent: HTMLElement
  _viewportDom: HTMLElement
  _lastViewbox: Box
  isOpen(): boolean
}

export function boundMinimap(
  minimap: Minimap,
  canvas: Canvas,
  navigate: (box: Box, smooth: boolean) => void,
): () => void {
  const originalUpdate = minimap._update
  const bounds = () => {
    const inner = canvas.viewbox().inner
    return paddedBounds(inner)
  }
  const update = () => {
    originalUpdate.call(minimap)
    if (!minimap.isOpen()) return
    const box = bounds()
    minimap._lastViewbox = box
    minimap._svg.setAttribute('viewBox', `${box.x} ${box.y} ${box.width} ${box.height}`)
    const mapRect = minimap._svg.getBoundingClientRect()
    const parentRect = minimap._parent.getBoundingClientRect()
    const viewport = projectViewport(canvas.viewbox(), box, mapRect)
    Object.assign(minimap._viewportDom.style, {
      left: `${mapRect.left - parentRect.left + viewport.x}px`,
      top: `${mapRect.top - parentRect.top + viewport.y}px`,
      width: `${viewport.width}px`,
      height: `${viewport.height}px`,
    })
  }
  minimap._update = update

  const diagramPoint = (event: MouseEvent) => {
    const matrix = minimap._svg.getScreenCTM()
    return matrix
      ? new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse())
      : null
  }
  let drag: { x: number; y: number } | undefined
  let frame = 0
  let desired: Box | undefined
  const move = (event: MouseEvent) => {
    if (!drag) return
    const point = diagramPoint(event)
    if (!point) return
    const viewbox = canvas.viewbox()
    desired = clampNavigation({ ...viewbox, x: point.x - drag.x, y: point.y - drag.y }, bounds())
    if (!frame)
      frame = requestAnimationFrame(() => {
        frame = 0
        if (desired) navigate(desired, false)
      })
  }
  const finish = () => {
    drag = undefined
    document.removeEventListener('mousemove', move)
    document.removeEventListener('mouseup', finish)
    update()
  }
  const down = (event: MouseEvent) => {
    if (event.button !== 0) return
    event.preventDefault()
    event.stopImmediatePropagation()
    const point = diagramPoint(event)
    if (!point) return
    const viewbox = canvas.viewbox()
    const onIndicator = (event.target as Element).closest('.viewport-dom')
    if (!onIndicator) {
      const target = clampNavigation(
        { ...viewbox, x: point.x - viewbox.width / 2, y: point.y - viewbox.height / 2 },
        bounds(),
      )
      navigate(target, true)
      // Клик по карте плавно центрирует; drag начинается только на рамке.
      return
    }
    drag = { x: point.x - viewbox.x, y: point.y - viewbox.y }
    document.addEventListener('mousemove', move)
    document.addEventListener('mouseup', finish)
  }
  const wheel = (event: WheelEvent) => {
    event.preventDefault()
    event.stopImmediatePropagation()
    if (!event.ctrlKey) return
    const viewbox = canvas.viewbox()
    const factor = Math.exp(-event.deltaY * (event.deltaMode === 0 ? 0.005 : 0.08))
    navigate(clampNavigation(zoomViewbox(viewbox.outer, viewbox, factor), bounds()), true)
  }
  minimap._parent.addEventListener('mousedown', down, true)
  minimap._parent.addEventListener('wheel', wheel, { capture: true, passive: false })
  return () => {
    finish()
    cancelAnimationFrame(frame)
    minimap._update = originalUpdate
    minimap._parent.removeEventListener('mousedown', down, true)
    minimap._parent.removeEventListener('wheel', wheel, true)
  }
}
