import BpmnRenderer from 'bpmn-js/lib/draw/BpmnRenderer'
import type PathMap from 'bpmn-js/lib/draw/PathMap'
import type TextRenderer from 'bpmn-js/lib/draw/TextRenderer'
import type { Connection, Element, Shape } from 'bpmn-js/lib/model/Types'
import type Canvas from 'diagram-js/lib/core/Canvas'
import type EventBus from 'diagram-js/lib/core/EventBus'
import type Styles from 'diagram-js/lib/draw/Styles'

/** Цвета по умолчанию для элементов без собственной раскраски (BPMN in Color). */
export interface RendererPalette {
  fill: string
  stroke: string
  label: string
}

type Attrs = Record<string, unknown>

/** Делегату не нужны подписки на события: рисование вызывает основной рендерер. */
const SILENT_EVENT_BUS = { on() {} } as unknown as EventBus

/**
 * BpmnRenderer с переключаемой палитрой.
 *
 * BpmnRenderer читает defaultFillColor/StrokeColor/LabelColor из `config.bpmnRenderer` один раз —
 * в замыкание конструктора. Чтобы сменить тему без пересоздания модели (и без потери истории правок),
 * рисование делегируется внутреннему экземпляру BpmnRenderer, который пересоздаётся с новыми цветами.
 * Сам этот класс регистрируется вместо стандартного `bpmnRenderer` и держит подписки на render.*.
 */
export class ThemedBpmnRenderer extends BpmnRenderer {
  static override $inject = [
    'config.bpmnRenderer',
    'eventBus',
    'styles',
    'pathMap',
    'canvas',
    'textRenderer',
  ]

  private delegate: BpmnRenderer
  private readonly createDelegate: (palette: RendererPalette) => BpmnRenderer

  constructor(
    config: { defaultFillColor?: string; defaultStrokeColor?: string; defaultLabelColor?: string },
    eventBus: EventBus,
    styles: Styles,
    pathMap: PathMap,
    canvas: Canvas,
    textRenderer: TextRenderer,
  ) {
    super(config, eventBus, styles, pathMap, canvas, textRenderer)
    this.createDelegate = (palette) =>
      new BpmnRenderer(
        {
          defaultFillColor: palette.fill,
          defaultStrokeColor: palette.stroke,
          defaultLabelColor: palette.label,
        },
        SILENT_EVENT_BUS,
        styles,
        pathMap,
        canvas,
        textRenderer,
      )
    this.delegate = this.createDelegate({
      fill: config?.defaultFillColor ?? '',
      stroke: config?.defaultStrokeColor ?? '',
      label: config?.defaultLabelColor ?? '',
    })
  }

  /** Новая палитра. Перерисовку элементов запускает вызывающий (событие elements.changed). */
  setPalette(palette: RendererPalette): void {
    this.delegate = this.createDelegate(palette)
  }

  override drawShape(parentGfx: SVGElement, element: Shape, attrs?: Attrs): SVGElement {
    return this.delegate.drawShape(parentGfx, element, attrs)
  }

  override drawConnection(parentGfx: SVGElement, element: Connection, attrs?: Attrs): SVGElement {
    return this.delegate.drawConnection(parentGfx, element, attrs)
  }

  override canRender(element: Element): boolean {
    return this.delegate.canRender(element)
  }
}

/** Модуль bpmn-js: подменяет стандартный `bpmnRenderer`. */
export const ThemedRendererModule = {
  __init__: ['bpmnRenderer'],
  bpmnRenderer: ['type', ThemedBpmnRenderer],
}
