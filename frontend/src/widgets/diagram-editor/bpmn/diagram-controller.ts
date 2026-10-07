import Modeler from 'bpmn-js/lib/Modeler'
import { BpmnPropertiesPanelModule, BpmnPropertiesProviderModule } from 'bpmn-js-properties-panel'
import TokenSimulationModule from 'bpmn-js-token-simulation'
import type Canvas from 'diagram-js/lib/core/Canvas'
import type ElementRegistry from 'diagram-js/lib/core/ElementRegistry'
import type EventBus from 'diagram-js/lib/core/EventBus'
import MinimapModule from 'diagram-js-minimap'
import { type ChangeEmitter, createChangeEmitter } from '../model/change-emitter'
import { embedStyle, loadEmbeddedFontCss, rasterizeSvg } from '../model/export-image'
import {
  diffMarkers,
  FOCUS_MARKER,
  type MarkerPlan,
  planMarkers,
  sameHighlights,
} from '../model/highlights'
import { animate, readMotion } from '../model/motion'
import {
  type DiagramTheme,
  observeTheme,
  primaryFontFamily,
  readDiagramTheme,
  sameTheme,
} from '../model/theme'
import {
  type Box,
  fitViewbox,
  focusViewbox,
  gridStep,
  interpolateViewbox,
  unionBox,
  zoomViewbox,
} from '../model/viewbox'
import type {
  DiagramEditorError,
  DiagramHighlights,
  DiagramImportResult,
  DiagramImportWarning,
  DiagramPoint,
  DiagramRemoteMove,
  DiagramRemoteSelection,
  DiagramSimulation,
  PngExportOptions,
} from '../types'
import { boundMinimap } from './bounded-minimap'
import { Playback } from './playback'
import { cleanPlaybackSvg, RuntimeColorsModule } from './runtime-colors'
import { SimulationLocalizationModule } from './simulation-localization'
import {
  type RendererPalette,
  type ThemedBpmnRenderer,
  ThemedRendererModule,
} from './themed-renderer'
import { TranslateModule } from './translate'

/** Задержка выдачи изменений наружу. */
const CHANGE_DELAY_MS = 400
/** Сколько держится подсветка после focusElement. */
const FOCUS_FLASH_MS = 1600
const ZOOM_STEP = 1.25
/** Сколько ждём загрузку шрифта перед первым импортом: подписи переносятся по его метрикам. */
const FONT_TIMEOUT_MS = 2000
/** Шаг сетки-подложки в единицах схемы, если нет токена `--grid-size`. */
const DEFAULT_GRID = 24

const SIMULATION_TOGGLE_EVENT = 'tokenSimulation.toggleMode'

export interface ControllerCallbacks {
  onChange?: (xml: string) => void
  onChangePending?: (pending: boolean) => void
  onSimulationChange?: (simulation: DiagramSimulation) => void
  onSimulationStart?: () => void
  onElementClick?: (elementId: string) => void
  onSelectionChange?: (elementIds: string[]) => void
  onViewportChange?: () => void
  onImport?: (result: DiagramImportResult) => void
  onError?: (error: DiagramEditorError) => void
  /** Первая схема открыта. */
  onReady?: () => void
}

interface CanvasLock {
  lock(): void
  unlock(): void
}

interface GraphicsCanvas {
  getGraphics(element: string | DiagramElement): SVGGraphicsElement | null
}

interface ToggleMode {
  toggleMode(active?: boolean): void
}

interface Minimap {
  toggle(open?: boolean): void
  isOpen(): boolean
}

interface PropertiesPanel {
  attachTo(container: HTMLElement): void
  detach(): void
}

/** Элемент реестра diagram-js: фигура (x, y, width, height) или соединение (waypoints). */
interface DiagramElement {
  id: string
  type: string
  x?: number
  y?: number
  width?: number
  height?: number
  waypoints?: Array<{ x: number; y: number }>
  labelTarget?: DiagramElement
}

function paletteOf(theme: DiagramTheme): RendererPalette {
  return { fill: theme.fill, stroke: theme.stroke, label: theme.label }
}

function boxOf(element: DiagramElement): Box | null {
  if (element.waypoints?.length) {
    const xs = element.waypoints.map((point) => point.x)
    const ys = element.waypoints.map((point) => point.y)
    const x = Math.min(...xs)
    const y = Math.min(...ys)
    return { x, y, width: Math.max(...xs) - x, height: Math.max(...ys) - y }
  }
  if (element.x === undefined || element.y === undefined) return null
  return { x: element.x, y: element.y, width: element.width ?? 0, height: element.height ?? 0 }
}

function toWarnings(warnings: unknown): DiagramImportWarning[] {
  if (!Array.isArray(warnings)) return []
  return warnings.map((warning: unknown) => {
    if (typeof warning === 'string') return { message: warning }
    const { message, element } = (warning ?? {}) as { message?: string; element?: { id?: string } }
    return { message: message ?? String(warning), elementId: element?.id }
  })
}

/**
 * Границы содержимого активного слоя. В типах diagram-js getActiveLayer описан как CanvasLayer,
 * но на деле возвращает SVG-группу слоя (так её использует и saveSVG в bpmn-js).
 */
function contentBox(canvas: Canvas): Box | null {
  const layer = canvas.getActiveLayer() as unknown as SVGGraphicsElement | null
  const bbox = layer?.getBBox()
  return bbox && bbox.width > 0 && bbox.height > 0 ? bbox : null
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/** Ждём шрифт подписей (латиница и кириллица), но не дольше FONT_TIMEOUT_MS. */
async function fontsReady(fontFamily: string): Promise<void> {
  const family = primaryFontFamily(fontFamily)
  if (!family || !document.fonts?.load) return
  const loading = document.fonts.load(`12px "${family}"`, 'Аа Zz 09').catch(() => undefined)
  await Promise.race([loading, delay(FONT_TIMEOUT_MS)])
}

/**
 * Обёртка над bpmn-js Modeler: импорт, тема, подсветка, экспорт, плагины.
 * React-компонент только передаёт сюда свойства — вся работа с bpmn-js живёт здесь.
 */
export class DiagramController {
  private readonly modeler: Modeler
  private readonly changes: ChangeEmitter
  private readonly playback: Playback
  private readonly disposers: Array<() => void> = []
  private readonly focusTimers = new Map<string, ReturnType<typeof setTimeout>>()
  private remoteMarkers = new Map<string, string>()
  private theme: DiagramTheme
  private markers: MarkerPlan = new Map()
  private remoteSelections: readonly DiagramRemoteSelection[] = []
  private remoteMoveTransforms = new Map<
    string,
    { graphics: SVGGraphicsElement; transform: string | null }
  >()
  private highlights: Partial<DiagramHighlights> | undefined
  /** Последний XML, который редактор показывает: импортированный или выданный в onChange. */
  private currentXml: string | undefined
  private pendingXml: string | undefined
  private importing = false
  private imported = false
  private readOnly = false
  private simulationActive = false
  private destroyed = false
  private propertiesHost: HTMLElement | null = null
  private stopAnimation: (() => void) | undefined
  private gridSize = DEFAULT_GRID
  private readonly root: HTMLElement
  private readonly callbacks: () => ControllerCallbacks

  constructor(root: HTMLElement, callbacks: () => ControllerCallbacks) {
    this.root = root
    this.callbacks = callbacks
    this.theme = readDiagramTheme(root)
    this.gridSize =
      Number.parseFloat(getComputedStyle(root).getPropertyValue('--grid-size')) || DEFAULT_GRID

    this.modeler = new Modeler({
      container: root,
      additionalModules: [
        ThemedRendererModule,
        TranslateModule,
        MinimapModule,
        TokenSimulationModule,
        RuntimeColorsModule,
        SimulationLocalizationModule,
        BpmnPropertiesPanelModule,
        BpmnPropertiesProviderModule,
      ],
      bpmnRenderer: {
        defaultFillColor: this.theme.fill,
        defaultStrokeColor: this.theme.stroke,
        defaultLabelColor: this.theme.label,
      },
      textRenderer: {
        defaultStyle: {
          fontFamily: this.theme.fontFamily,
          fontSize: 12,
          fontWeight: 'normal',
          lineHeight: 1.2,
        },
      },
      minimap: { open: false },
      animation: { randomize: false },
    })

    this.changes = createChangeEmitter({
      delay: CHANGE_DELAY_MS,
      serialize: () => this.serialize(),
      onChange: (xml) => {
        this.currentXml = xml
        this.callbacks().onChange?.(xml)
      },
      onChangePending: (pending) => this.callbacks().onChangePending?.(pending),
      onError: (cause) => this.report('export', 'Не удалось сохранить изменения схемы.', cause),
    })

    const eventBus = this.service<EventBus>('eventBus')
    eventBus.on('commandStack.changed', (event: { trigger?: string }) => {
      if (!this.readOnly && !this.importing) this.changes.notify(event.trigger)
    })
    eventBus.on('element.click', (event: { element: DiagramElement }) => this.handleClick(event))
    eventBus.on('selection.changed', (event: { newSelection?: DiagramElement[] }) =>
      this.callbacks().onSelectionChange?.((event.newSelection ?? []).map((element) => element.id)),
    )
    eventBus.on(
      'canvas.viewbox.changed',
      (event: { viewbox: { x: number; y: number; scale: number } }) => {
        this.syncGrid(event.viewbox)
        this.callbacks().onViewportChange?.()
      },
    )
    // После штатного обработчика симуляции (приоритет 1000), который снимает блокировку холста.
    eventBus.on(SIMULATION_TOGGLE_EVENT, 500, (event: { active: boolean }) => {
      this.simulationActive = event.active
      root.classList.toggle('de-simulating', event.active)
      if (!event.active && this.readOnly) this.service<CanvasLock>('canvasLock').lock()
    })

    this.playback = new Playback(
      this.modeler,
      (state) => this.callbacks().onSimulationChange?.(state),
      () => this.callbacks().onSimulationStart?.(),
    )
    this.disposers.push(
      boundMinimap(this.service('minimap'), this.service('canvas'), (box, smooth) => {
        if (smooth) this.animateTo(box)
        else {
          this.stopAnimation?.()
          this.service<Canvas>('canvas').viewbox(box)
        }
      }),
    )

    this.disposers.push(observeTheme(() => this.applyTheme()))
  }

  // --- Свойства React-компонента ---

  /** Новый XML от экрана. Тот же XML, что мы только что отдали в onChange, не перечитывается. */
  setXml(xml: string): void {
    if (this.destroyed || xml === this.currentXml) return
    this.pendingXml = xml
    if (!this.importing) void this.drainImports()
  }

  setReadOnly(readOnly: boolean): void {
    this.readOnly = readOnly
    this.root.classList.toggle('de-readonly', readOnly)
    const lock = this.service<CanvasLock>('canvasLock')
    if (readOnly) lock.lock()
    else if (!this.simulationActive) lock.unlock()
    if (this.propertiesHost) this.propertiesHost.inert = readOnly
  }

  setHighlights(highlights: Partial<DiagramHighlights> | undefined): void {
    if (sameHighlights(this.highlights, highlights)) return
    this.highlights = highlights
    if (this.imported) this.applyHighlights()
  }

  // --- Императивное API ---

  fit(): void {
    const canvas = this.service<Canvas>('canvas')
    const bbox = contentBox(canvas)
    if (bbox) this.animateTo(fitViewbox(canvas.viewbox().outer, bbox))
  }

  zoomIn(): void {
    this.zoomBy(ZOOM_STEP)
  }

  zoomOut(): void {
    this.zoomBy(1 / ZOOM_STEP)
  }

  focusElement(ids: string | readonly string[]): boolean {
    const registry = this.service<ElementRegistry>('elementRegistry')
    const elements = (typeof ids === 'string' ? [ids] : ids)
      .map((id) => registry.get(id) as DiagramElement | undefined)
      .filter((element): element is DiagramElement => Boolean(element))
    const bbox = unionBox(elements.map(boxOf).filter((box): box is Box => box !== null))
    if (!bbox) return false
    const canvas = this.service<Canvas>('canvas')
    const viewbox = canvas.viewbox()
    this.animateTo(focusViewbox(viewbox.outer, viewbox, bbox))
    for (const element of elements) this.flash(element.id)
    return true
  }

  screenToDiagram(clientX: number, clientY: number): DiagramPoint {
    const viewbox = this.service<Canvas>('canvas').viewbox()
    const rect = this.root.getBoundingClientRect()
    return {
      x: viewbox.x + (clientX - rect.left) / viewbox.scale,
      y: viewbox.y + (clientY - rect.top) / viewbox.scale,
    }
  }

  diagramToScreen(point: DiagramPoint): DiagramPoint {
    const viewbox = this.service<Canvas>('canvas').viewbox()
    const rect = this.root.getBoundingClientRect()
    return {
      x: rect.left + (point.x - viewbox.x) * viewbox.scale,
      y: rect.top + (point.y - viewbox.y) * viewbox.scale,
    }
  }

  setRemoteSelections(selections: readonly DiagramRemoteSelection[]): void {
    this.remoteSelections = selections
    this.applyRemoteSelections()
  }

  setRemoteMoves(moves: readonly DiagramRemoteMove[]): void {
    for (const { graphics, transform } of this.remoteMoveTransforms.values()) {
      if (transform === null) graphics.removeAttribute('transform')
      else graphics.setAttribute('transform', transform)
      graphics.classList.remove('de-collab-moving')
    }
    this.remoteMoveTransforms.clear()
    if (!this.imported) return

    const canvas = this.service<GraphicsCanvas>('canvas')
    const registry = this.service<ElementRegistry>('elementRegistry')
    for (const move of moves) {
      for (const id of move.elementIds) {
        const element = registry.get(id) as DiagramElement | undefined
        if (!element || element.type === 'label' || element.type.includes('SequenceFlow')) continue
        const graphics = canvas.getGraphics(element)
        if (!graphics || this.remoteMoveTransforms.has(id)) continue
        const transform = graphics.getAttribute('transform')
        this.remoteMoveTransforms.set(id, { graphics, transform })
        graphics.setAttribute(
          'transform',
          `translate(${move.delta.x} ${move.delta.y})${transform ? ` ${transform}` : ''}`,
        )
        graphics.classList.add('de-collab-moving')
      }
    }
  }

  private applyRemoteSelections(): void {
    if (!this.imported) return
    const canvas = this.service<Canvas>('canvas')
    const registry = this.service<ElementRegistry>('elementRegistry')
    const next = new Map<string, string>()
    for (const selection of this.remoteSelections) {
      const colorKey = Math.abs(Math.trunc(selection.colorKey)) % 8
      const marker = `de-collab-selection-${colorKey}`
      for (const id of selection.elementIds) next.set(id, marker)
    }
    for (const [id, marker] of this.remoteMarkers) {
      if (next.get(id) !== marker && registry.get(id)) canvas.removeMarker(id, marker)
    }
    for (const [id, marker] of next) {
      if (this.remoteMarkers.get(id) !== marker && registry.get(id)) canvas.addMarker(id, marker)
    }
    this.remoteMarkers = next
  }

  exportXml(): Promise<string> {
    return this.serialize()
  }

  cancelPendingChanges(): void {
    this.changes.cancel()
  }

  async exportSvg(): Promise<string> {
    const { svg } = await this.modeler.saveSVG()
    // Без встроенного шрифта SVG всё равно корректен, просто подписи будут системным шрифтом.
    const fontCss = await loadEmbeddedFontCss(this.theme.fontFamily).catch(() => '')
    return embedStyle(cleanPlaybackSvg(svg), fontCss)
  }

  async exportPng(scale = 2, options: PngExportOptions = {}): Promise<Blob> {
    const background =
      (options.background ?? 'surface') === 'surface' ? this.theme.background : undefined
    return rasterizeSvg(await this.exportSvg(), scale, background)
  }

  toggleMinimap(open?: boolean): boolean {
    const minimap = this.service<Minimap>('minimap')
    minimap.toggle(open ?? !minimap.isOpen())
    return minimap.isOpen()
  }

  toggleSimulation(active?: boolean): boolean {
    const next = active ?? !this.simulationActive
    this.service<ToggleMode>('toggleMode').toggleMode(next)
    if (next) this.playback.autoStart()
    return this.simulationActive
  }

  startSimulation(id?: string): void {
    this.playback.start(id)
  }
  pauseSimulation(): void {
    this.playback.pause()
  }
  resetSimulation(): void {
    this.playback.reset()
  }
  chooseSimulationFlow(id: string): void {
    this.playback.choose(id)
  }
  triggerSimulationEvent(id: string): void {
    this.playback.trigger(id)
  }

  setPropertiesPanel(container: HTMLElement | null): void {
    const panel = this.service<PropertiesPanel>('propertiesPanel')
    panel.detach()
    this.propertiesHost?.remove()
    this.propertiesHost = null
    if (!container || this.destroyed) return
    const host = document.createElement('div')
    host.className = 'de-properties'
    host.inert = this.readOnly
    container.appendChild(host)
    panel.attachTo(host)
    this.propertiesHost = host
  }

  destroy(): void {
    if (this.destroyed) return
    this.destroyed = true
    this.playback.destroy()
    if (this.simulationActive) this.service<ToggleMode>('toggleMode').toggleMode(false)
    this.stopAnimation?.()
    for (const timer of this.focusTimers.values()) clearTimeout(timer)
    for (const dispose of this.disposers) dispose()
    this.propertiesHost?.remove()
    // Несохранённая правка (последние 400 мс) уходит наружу до разрушения модели.
    void this.changes.flush().finally(() => this.modeler.destroy())
  }

  // --- Внутреннее ---

  private service<T>(name: string): T {
    return this.modeler.get<T>(name)
  }

  private async serialize(): Promise<string> {
    const { xml } = await this.modeler.saveXML({ format: true })
    if (xml === undefined) throw new Error('bpmn-js не вернул XML')
    return xml
  }

  private async drainImports(): Promise<void> {
    this.importing = true
    try {
      await fontsReady(this.theme.fontFamily)
      while (this.pendingXml !== undefined && !this.destroyed) {
        const xml = this.pendingXml
        this.pendingXml = undefined
        await this.runImport(xml)
      }
    } finally {
      this.importing = false
    }
  }

  private async runImport(xml: string): Promise<void> {
    // Останавливаем до import.parse.start: библиотека иначе автоматически включает старый режим.
    if (this.simulationActive) this.service<ToggleMode>('toggleMode').toggleMode(false)
    const first = !this.imported
    const canvas = this.service<Canvas>('canvas')
    const keepViewbox = first ? null : canvas.viewbox()
    this.setRemoteMoves([])
    this.changes.cancel()
    try {
      const { warnings } = await this.modeler.importXML(xml)
      if (this.destroyed) return
      this.currentXml = xml
      this.imported = true
      this.changes.setBaseline(await this.serialize())
      this.markers = new Map()
      this.applyHighlights()
      this.applyRemoteSelections()
      if (keepViewbox) canvas.viewbox(keepViewbox)
      else this.fitNow()
      this.callbacks().onImport?.({ warnings: toWarnings(warnings) })
      if (first) this.callbacks().onReady?.()
    } catch (cause) {
      if (this.destroyed) return
      const warnings = toWarnings((cause as { warnings?: unknown })?.warnings)
      this.report(
        'import',
        'Схема не открылась: XML повреждён или это не BPMN 2.0.',
        cause,
        warnings,
      )
    }
  }

  private report(
    kind: DiagramEditorError['kind'],
    message: string,
    cause: unknown,
    warnings: DiagramImportWarning[] = [],
  ): void {
    this.callbacks().onError?.({ kind, message, warnings, cause })
  }

  private handleClick(event: { element: DiagramElement }): void {
    const element = event.element.labelTarget ?? event.element
    const root = this.service<Canvas>('canvas').getRootElement() as unknown as DiagramElement
    if (element.id === root.id || element.type === 'label') return
    this.callbacks().onElementClick?.(element.id)
  }

  private applyHighlights(): void {
    const canvas = this.service<Canvas>('canvas')
    const registry = this.service<ElementRegistry>('elementRegistry')
    const plan = planMarkers(this.highlights)
    const { add, remove } = diffMarkers(this.markers, plan)
    for (const [id, marker] of remove) if (registry.get(id)) canvas.removeMarker(id, marker)
    for (const [id, marker] of add) if (registry.get(id)) canvas.addMarker(id, marker)
    this.markers = plan
  }

  /** Короткая подсветка элемента; повторный вызов перезапускает анимацию. */
  private flash(id: string): void {
    const canvas = this.service<Canvas>('canvas')
    const previous = this.focusTimers.get(id)
    if (previous) clearTimeout(previous)
    canvas.removeMarker(id, FOCUS_MARKER)
    requestAnimationFrame(() => {
      if (this.destroyed || !this.service<ElementRegistry>('elementRegistry').get(id)) return
      canvas.addMarker(id, FOCUS_MARKER)
      this.focusTimers.set(
        id,
        setTimeout(() => {
          this.focusTimers.delete(id)
          if (!this.destroyed && this.service<ElementRegistry>('elementRegistry').get(id))
            canvas.removeMarker(id, FOCUS_MARKER)
        }, FOCUS_FLASH_MS),
      )
    })
  }

  private zoomBy(factor: number): void {
    const viewbox = this.service<Canvas>('canvas').viewbox()
    this.animateTo(zoomViewbox(viewbox.outer, viewbox, factor))
  }

  private fitNow(): void {
    const canvas = this.service<Canvas>('canvas')
    const bbox = contentBox(canvas)
    if (bbox) canvas.viewbox(fitViewbox(canvas.viewbox().outer, bbox))
  }

  private animateTo(target: Box): void {
    this.stopAnimation?.()
    const canvas = this.service<Canvas>('canvas')
    const from = canvas.viewbox()
    this.stopAnimation = animate(readMotion(this.root), (progress) => {
      if (!this.destroyed) canvas.viewbox(interpolateViewbox(from, target, progress))
    })
  }

  /** Сетка-подложка двигается и масштабируется вместе со схемой (CSS-переменные на корне). */
  private syncGrid(viewbox: { x: number; y: number; scale: number }): void {
    const step = gridStep(this.gridSize * viewbox.scale)
    const offset = (value: number) => `${(((-value * viewbox.scale) % step) + step) % step}px`
    this.root.style.setProperty('--de-scale', String(viewbox.scale))
    this.root.style.setProperty('--de-grid-step', `${step}px`)
    this.root.style.setProperty('--de-grid-x', offset(viewbox.x))
    this.root.style.setProperty('--de-grid-y', offset(viewbox.y))
  }

  private applyTheme(): void {
    if (this.destroyed) return
    const next = readDiagramTheme(this.root)
    if (sameTheme(next, this.theme)) return
    this.theme = next
    this.service<ThemedBpmnRenderer>('bpmnRenderer').setPalette(paletteOf(next))
    this.refreshSimulationColors()
    const registry = this.service<ElementRegistry>('elementRegistry')
    this.service<EventBus>('eventBus').fire('elements.changed', { elements: registry.getAll() })
  }

  /**
   * Симуляция кэширует свои цвета из CSS-переменных при первом чтении.
   * После смены темы сбрасываем кэш и, если симуляция идёт, заново красим элементы.
   */
  private refreshSimulationColors(): void {
    const styles = this.modeler.get<{
      _cache?: Record<string, string>
      _computedStyle?: CSSStyleDeclaration
    } | null>('simulationStyles', false)
    if (styles?._cache) {
      styles._cache = {}
      styles._computedStyle = undefined
    }
    if (!this.simulationActive) return
    const neutral = this.modeler.get<{ _setNeutralColors?: () => void } | null>(
      'neutralElementColors',
      false,
    )
    neutral?._setNeutralColors?.()
  }
}
