import type { ReactNode, Ref } from 'react'

/**
 * Подсветка элементов схемы. Значения — id элементов BPMN (`Task_1`, `Flow_2`…).
 * Неизвестные id молча пропускаются: схема могла измениться раньше, чем пришли данные.
 */
export interface DiagramHighlights {
  /** Элементы, построенные на допущении (вопрос проигнорирован): янтарный пунктир. */
  assumptions: readonly string[]
  /** Элементы выбранного вопроса: акцентная обводка «Ток». */
  selected: readonly string[]
  /** Элементы, добавленные в новой версии схемы: «Хвоя». */
  added: readonly string[]
}

/** Предупреждение импорта: схема открылась, но часть элементов bpmn-js пропустил. */
export interface DiagramImportWarning {
  message: string
  /** id элемента, к которому относится предупреждение, если bpmn-js его сообщил. */
  elementId?: string
}

export interface DiagramImportResult {
  warnings: readonly DiagramImportWarning[]
}

export interface DiagramEditorError {
  /** `import` — XML не открылся; `export` — не удалось выгрузить XML, SVG или PNG. */
  kind: 'import' | 'export'
  message: string
  warnings: readonly DiagramImportWarning[]
  cause: unknown
}

/** Фон PNG: `surface` — цвет токена `--color-surface`, `transparent` — без фона. */
export type PngBackground = 'surface' | 'transparent'

export interface PngExportOptions {
  background?: PngBackground
}

export interface DiagramPoint {
  x: number
  y: number
}

export interface DiagramRemoteSelection {
  colorKey: number
  elementIds: readonly string[]
}

/** Временное положение фигур во время перетаскивания другим участником. */
export interface DiagramRemoteMove {
  elementIds: readonly string[]
  delta: DiagramPoint
}

export interface SimulationOption {
  id: string
  label: string
}

/** Состояние локального воспроизведения; скорости и позиции не сохраняются в BPMN. */
export interface DiagramSimulation {
  active: boolean
  paused: boolean
  status: 'ready' | 'playing' | 'paused' | 'waiting' | 'completed'
  starts: readonly SimulationOption[]
  choices: readonly SimulationOption[]
  choiceLabel?: string
  waiting: readonly SimulationOption[]
  message?: string
}

/** Императивное API редактора. Доступно через `ref` и в `onReady`. */
export interface DiagramEditorHandle {
  /** Вписать схему в окно (плавно, с отступами, без увеличения больше 100 %). */
  fit(): void
  zoomIn(): void
  zoomOut(): void
  /**
   * Плавно центрирует элемент (или несколько) и коротко подсвечивает его.
   * Возвращает `false`, если ни одного элемента с такими id нет на схеме.
   */
  focusElement(id: string | readonly string[]): boolean
  /** Перевести координаты указателя браузера в координаты диаграммы. */
  screenToDiagram(clientX: number, clientY: number): DiagramPoint
  /** Перевести координаты диаграммы в координаты окна браузера. */
  diagramToScreen(point: DiagramPoint): DiagramPoint
  /** Подсветить фигуры, выбранные участниками комнаты. */
  setRemoteSelections(selections: readonly DiagramRemoteSelection[]): void
  /** Показать временное перемещение фигур, не меняя XML и сохранённую версию. */
  setRemoteMoves(moves: readonly DiagramRemoteMove[]): void
  /** BPMN 2.0 XML с отступами. */
  exportXml(): Promise<string>
  /** Отменить ещё не выданный XML после явного отказа от локального черновика. */
  cancelPendingChanges(): void
  /** Самодостаточный SVG: цвета текущей темы, шрифт встроен. */
  exportSvg(): Promise<string>
  /** PNG через canvas. `scale` по умолчанию 2. */
  exportPng(scale?: number, options?: PngExportOptions): Promise<Blob>
  /** Показать или скрыть мини-карту. Без аргумента переключает. Возвращает новое состояние. */
  toggleMinimap(open?: boolean): boolean
  /** Включить или выключить симуляцию токена. Без аргумента переключает. Возвращает новое состояние. */
  toggleSimulation(active?: boolean): boolean
  startSimulation(startId?: string): void
  pauseSimulation(): void
  resetSimulation(): void
  chooseSimulationFlow(flowId: string): void
  triggerSimulationEvent(elementId: string): void
  /** Отрисовать панель свойств в контейнере экрана; `null` — убрать её. */
  setPropertiesPanel(container: HTMLElement | null): void
}

export interface DiagramEditorProps {
  /** BPMN 2.0 XML. Смена значения перечитывает схему в том же редакторе (без пересоздания). */
  xml: string
  /**
   * Схема изменилась (правка, отмена, повтор). Вызывается не чаще раза в 400 мс
   * и только если XML действительно стал другим. Возврат этого XML обратно в `xml` не перечитывает схему.
   */
  onChange?: (xml: string) => void
  /** Синхронно отметить команду до onChange; false — XML выдан, правка отменена или импортирована. */
  onChangePending?: (pending: boolean) => void
  /** Включение режима, пауза, ожидание и завершение. */
  onSimulationChange?: (simulation: DiagramSimulation) => void
  /** Реально создан экземпляр процесса (включение режима без запуска сюда не приходит). */
  onSimulationStart?: () => void
  /** Только просмотр: нет палитры, правок, контекстного меню; панель свойств неактивна. */
  readOnly?: boolean
  highlights?: Partial<DiagramHighlights>
  /** Клик по элементу схемы (не по пустому полю). Для подписи приходит id её элемента. */
  onElementClick?: (elementId: string) => void
  /** Выбранные фигуры и соединения BPMN. */
  onSelectionChange?: (elementIds: string[]) => void
  /** Изменилась видимая область схемы (pan/zoom). */
  onViewportChange?: () => void
  /** Первая схема открыта, API готово. */
  onReady?: (handle: DiagramEditorHandle) => void
  /** Схема открыта (после каждого импорта), с предупреждениями bpmn-js. */
  onImport?: (result: DiagramImportResult) => void
  onError?: (error: DiagramEditorError) => void
  className?: string
  /** Подпись области для скринридеров. */
  ariaLabel?: string
}

export interface LazyDiagramEditorProps extends DiagramEditorProps {
  ref?: Ref<DiagramEditorHandle>
  /** Что показать, пока грузится чанк редактора. По умолчанию — пустой блок того же размера. */
  fallback?: ReactNode
}
