import type { DiagramHighlights } from '../types'

/**
 * CSS-классы маркеров, которые вешаются на элементы через `canvas.addMarker`.
 * Префикс `hl-` обязателен: diagram-js сам использует маркеры `selected`, `hover`, `attach-ok`…,
 * и голое имя `selected` снималось бы при каждом снятии выделения.
 */
export const HIGHLIGHT_MARKERS = {
  assumptions: 'hl-assumption',
  selected: 'hl-selected',
  added: 'hl-added',
} as const satisfies Record<keyof DiagramHighlights, string>

/** Короткая подсветка после `focusElement`. */
export const FOCUS_MARKER = 'hl-focus'

/** id элемента и набор классов-маркеров. */
export type MarkerPlan = Map<string, Set<string>>

export interface MarkerDiff {
  add: Array<[elementId: string, marker: string]>
  remove: Array<[elementId: string, marker: string]>
}

const KINDS = Object.keys(HIGHLIGHT_MARKERS) as Array<keyof DiagramHighlights>

/** Раскладывает подсветку по элементам: какие маркеры должны висеть на каждом id. */
export function planMarkers(highlights: Partial<DiagramHighlights> | undefined): MarkerPlan {
  const plan: MarkerPlan = new Map()
  for (const kind of KINDS) {
    for (const id of highlights?.[kind] ?? []) {
      if (!id) continue
      const markers = plan.get(id) ?? new Set<string>()
      markers.add(HIGHLIGHT_MARKERS[kind])
      plan.set(id, markers)
    }
  }
  return plan
}

/** Минимальный набор операций, чтобы перейти от одной подсветки к другой без мигания. */
export function diffMarkers(prev: MarkerPlan, next: MarkerPlan): MarkerDiff {
  const diff: MarkerDiff = { add: [], remove: [] }
  for (const [id, markers] of prev) {
    const keep = next.get(id)
    for (const marker of markers) if (!keep?.has(marker)) diff.remove.push([id, marker])
  }
  for (const [id, markers] of next) {
    const had = prev.get(id)
    for (const marker of markers) if (!had?.has(marker)) diff.add.push([id, marker])
  }
  return diff
}

/** Сравнение по содержимому: экран может передавать новый объект на каждый рендер. */
export function sameHighlights(
  a: Partial<DiagramHighlights> | undefined,
  b: Partial<DiagramHighlights> | undefined,
): boolean {
  return KINDS.every((kind) => {
    const left = a?.[kind] ?? []
    const right = b?.[kind] ?? []
    return left.length === right.length && left.every((id, index) => id === right[index])
  })
}
