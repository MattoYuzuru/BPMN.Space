import type { Box, Size } from './viewbox'

export const MINIMAP_PADDING = 72

export function paddedBounds(bounds: Box, padding = MINIMAP_PADDING): Box {
  return {
    x: bounds.x - padding,
    y: bounds.y - padding,
    width: Math.max(1, bounds.width) + padding * 2,
    height: Math.max(1, bounds.height) + padding * 2,
  }
}

/** Большую ось центрируем, маленькую ограничиваем границами схемы с отступом. */
export function clampNavigation(viewport: Box, bounds: Box): Box {
  const axis = (position: number, length: number, start: number, span: number) =>
    length >= span
      ? start + (span - length) / 2
      : Math.min(start + span - length, Math.max(start, position))
  return {
    ...viewport,
    x: axis(viewport.x, viewport.width, bounds.x, bounds.width),
    y: axis(viewport.y, viewport.height, bounds.y, bounds.height),
  }
}

/** SVG meet сохраняет пропорции; рамка целиком внутри карты, включая большой viewport. */
export function projectViewport(viewport: Box, bounds: Box, map: Size, inset = 3): Box {
  const scale = Math.min(map.width / bounds.width, map.height / bounds.height)
  const offsetX = (map.width - bounds.width * scale) / 2
  const offsetY = (map.height - bounds.height * scale) / 2
  const minWidth = Math.min(2, Math.max(0, map.width - inset * 2))
  const minHeight = Math.min(2, Math.max(0, map.height - inset * 2))
  const x = Math.min(
    map.width - inset - minWidth,
    Math.max(inset, offsetX + (viewport.x - bounds.x) * scale),
  )
  const y = Math.min(
    map.height - inset - minHeight,
    Math.max(inset, offsetY + (viewport.y - bounds.y) * scale),
  )
  const right = Math.max(
    x,
    Math.min(map.width - inset, offsetX + (viewport.x + viewport.width - bounds.x) * scale),
  )
  const bottom = Math.max(
    y,
    Math.min(map.height - inset, offsetY + (viewport.y + viewport.height - bounds.y) * scale),
  )
  return { x, y, width: Math.max(minWidth, right - x), height: Math.max(minHeight, bottom - y) }
}
