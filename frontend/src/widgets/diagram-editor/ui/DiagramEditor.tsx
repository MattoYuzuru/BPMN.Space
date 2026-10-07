import '@fontsource-variable/geist'
import 'bpmn-js/dist/assets/diagram-js.css'
import 'bpmn-js/dist/assets/bpmn-js.css'
import 'bpmn-js/dist/assets/bpmn-font/css/bpmn.css'
import 'diagram-js-minimap/assets/diagram-js-minimap.css'
import 'bpmn-js-token-simulation/assets/css/bpmn-js-token-simulation.css'
import '@bpmn-io/properties-panel/dist/assets/properties-panel.css'
import './styles/index.css'

import { type Ref, useEffect, useImperativeHandle, useLayoutEffect, useRef, useState } from 'react'
import { cn } from '@/shared/lib/cn'
import { DiagramController } from '../bpmn/diagram-controller'
import { EMPTY_SIMULATION } from '../bpmn/playback'
import type { DiagramEditorHandle, DiagramEditorProps } from '../types'
import { SimulationControls } from './SimulationControls'

const NOT_READY = 'Редактор схемы ещё не загрузился'

/**
 * Редактор BPMN на bpmn-js. Грузится отдельным чанком через `LazyDiagramEditor` —
 * напрямую этот модуль не импортируйте, иначе bpmn-js попадёт в стартовый бандл.
 */
export default function DiagramEditor({
  ref,
  xml,
  onChange,
  onChangePending,
  onSimulationStart,
  onSimulationChange,
  onSelectionChange,
  onViewportChange,
  readOnly = false,
  highlights,
  onElementClick,
  onReady,
  onImport,
  onError,
  className,
  ariaLabel = 'Схема процесса',
}: DiagramEditorProps & { ref?: Ref<DiagramEditorHandle> }) {
  const [simulation, setSimulation] = useState(EMPTY_SIMULATION)
  const rootRef = useRef<HTMLElement>(null)
  const controllerRef = useRef<DiagramController | null>(null)
  const callbacksRef = useRef({
    onChange,
    onChangePending,
    onSimulationStart,
    onSimulationChange,
    onElementClick,
    onSelectionChange,
    onViewportChange,
    onImport,
    onError,
    onReady,
  })
  const readOnlyRef = useRef(readOnly)
  // Контейнер панели свойств переживает пересоздание контроллера (StrictMode, горячая перезагрузка).
  const panelRef = useRef<HTMLElement | null>(null)

  useLayoutEffect(() => {
    callbacksRef.current = {
      onChange,
      onChangePending,
      onSimulationStart,
      onSimulationChange,
      onElementClick,
      onSelectionChange,
      onViewportChange,
      onImport,
      onError,
      onReady,
    }
    readOnlyRef.current = readOnly
  })

  // Методы обращаются к контроллеру в момент вызова: ссылка стабильна на всё время жизни компонента.
  const handleRef = useRef<DiagramEditorHandle | null>(null)
  handleRef.current ??= createHandle(
    () => controllerRef.current,
    (container) => {
      panelRef.current = container
    },
  )
  const handle = handleRef.current

  useImperativeHandle(ref, () => handle, [handle])

  useEffect(() => {
    const root = rootRef.current
    if (!root) return
    const controller = new DiagramController(root, () => ({
      ...callbacksRef.current,
      onSimulationChange: (state) => {
        setSimulation(state)
        callbacksRef.current.onSimulationChange?.(state)
      },
      onReady: () => callbacksRef.current.onReady?.(handle),
    }))
    controller.setReadOnly(readOnlyRef.current)
    if (panelRef.current) controller.setPropertiesPanel(panelRef.current)
    controllerRef.current = controller
    return () => {
      controllerRef.current = null
      controller.destroy()
    }
  }, [handle])

  useEffect(() => {
    controllerRef.current?.setXml(xml)
  }, [xml])

  useEffect(() => {
    controllerRef.current?.setReadOnly(readOnly)
  }, [readOnly])

  useEffect(() => {
    controllerRef.current?.setHighlights(highlights)
  }, [highlights])

  return (
    <section ref={rootRef} aria-label={ariaLabel} className={cn('de-root font-sans', className)}>
      <SimulationControls state={simulation} handle={handle} />
    </section>
  )
}

function createHandle(
  get: () => DiagramController | null,
  rememberPanel: (container: HTMLElement | null) => void,
): DiagramEditorHandle {
  const ensure = () => {
    const controller = get()
    if (!controller) throw new Error(NOT_READY)
    return controller
  }
  return {
    fit: () => get()?.fit(),
    zoomIn: () => get()?.zoomIn(),
    zoomOut: () => get()?.zoomOut(),
    focusElement: (id) => get()?.focusElement(id) ?? false,
    screenToDiagram: (clientX, clientY) =>
      get()?.screenToDiagram(clientX, clientY) ?? { x: 0, y: 0 },
    diagramToScreen: (point) => get()?.diagramToScreen(point) ?? { x: 0, y: 0 },
    setRemoteSelections: (selections) => get()?.setRemoteSelections(selections),
    setRemoteMoves: (moves) => get()?.setRemoteMoves(moves),
    exportXml: async () => ensure().exportXml(),
    cancelPendingChanges: () => get()?.cancelPendingChanges(),
    exportSvg: async () => ensure().exportSvg(),
    exportPng: async (scale, options) => ensure().exportPng(scale, options),
    toggleMinimap: (open) => get()?.toggleMinimap(open) ?? false,
    toggleSimulation: (active) => get()?.toggleSimulation(active) ?? false,
    startSimulation: (id) => get()?.startSimulation(id),
    pauseSimulation: () => get()?.pauseSimulation(),
    resetSimulation: () => get()?.resetSimulation(),
    chooseSimulationFlow: (id) => get()?.chooseSimulationFlow(id),
    triggerSimulationEvent: (id) => get()?.triggerSimulationEvent(id),
    setPropertiesPanel: (container) => {
      rememberPanel(container)
      get()?.setPropertiesPanel(container)
    },
  }
}
