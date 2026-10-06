import type Canvas from 'diagram-js/lib/core/Canvas'
import type ElementRegistry from 'diagram-js/lib/core/ElementRegistry'
import type EventBus from 'diagram-js/lib/core/EventBus'

interface Colors {
  fill?: string
  stroke?: string
  priority: number
}

/** Цвета симуляции только в DOM: служебная раскраска никогда не пишет BPMN DI. */
class RuntimeColors {
  static $inject = ['elementRegistry', 'eventBus', 'canvas']
  private colors = new Map<string, Map<string, Colors>>()
  private readonly registry: ElementRegistry
  private readonly canvas: Canvas
  constructor(registry: ElementRegistry, bus: EventBus, canvas: Canvas) {
    this.registry = registry
    this.canvas = canvas
    bus.on('tokenSimulation.toggleMode', 50000, () => this.clear())
    bus.on('diagram.clear', () => this.clear())
    bus.on('elements.changed', 250, () => {
      for (const id of this.colors.keys()) this.apply(id)
    })
  }
  add(element: { id: string }, id: string, colors: Omit<Colors, 'priority'>, priority = 1000) {
    const entries = this.colors.get(element.id) ?? new Map<string, Colors>()
    entries.set(id, { ...colors, priority })
    this.colors.set(element.id, entries)
    this.apply(element.id)
  }
  remove(element: { id: string }, id: string) {
    this.colors.get(element.id)?.delete(id)
    this.apply(element.id)
  }
  private apply(id: string) {
    if (!this.registry.get(id)) return
    const graphics = this.registry.getGraphics(id) as unknown as SVGElement
    const colors = [...(this.colors.get(id)?.values() ?? [])].sort(
      (a, b) => b.priority - a.priority,
    )[0]
    if (colors) this.canvas.addMarker(id, 'de-simulation-color')
    else this.canvas.removeMarker(id, 'de-simulation-color')
    for (const key of ['fill', 'stroke'] as const) {
      if (colors?.[key]) graphics.style.setProperty(`--de-sim-${key}`, colors[key])
      else graphics.style.removeProperty(`--de-sim-${key}`)
    }
  }
  private clear() {
    for (const id of this.colors.keys()) {
      this.colors.set(id, new Map())
      this.apply(id)
    }
    this.colors.clear()
  }
}

/** Убираем временные SVG-группы и DOM-цвета из SVG/PNG, не сбрасывая запущенный сценарий. */
export function cleanPlaybackSvg(svg: string): string {
  const document = new DOMParser().parseFromString(svg, 'image/svg+xml')
  for (const element of document.querySelectorAll('.bts-animation-tokens')) element.remove()
  document
    .querySelectorAll('.de-simulation-color, .de-playback-active, .de-playback-root-start')
    .forEach((element) => {
      element.classList.remove(
        'de-simulation-color',
        'de-playback-active',
        'de-playback-root-start',
      )
      if (element instanceof SVGElement) {
        element.style.removeProperty('--de-sim-fill')
        element.style.removeProperty('--de-sim-stroke')
      } else {
        // DOMParser XMLDocument не всегда создаёт экземпляр SVGElement.
        element.setAttribute(
          'style',
          (element.getAttribute('style') ?? '').replace(/--de-sim-(?:fill|stroke):[^;]+;?/g, ''),
        )
      }
    })
  return new XMLSerializer().serializeToString(document)
}

export const RuntimeColorsModule = { elementColors: ['type', RuntimeColors] }
