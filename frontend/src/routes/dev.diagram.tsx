import { createFileRoute } from '@tanstack/react-router'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  type DiagramEditorHandle,
  type DiagramHighlights,
  LazyDiagramEditor,
} from '@/widgets/diagram-editor'

/**
 * Демо редактора схемы для ручной и автоматической проверки виджета (без кнопок: управление —
 * через window.__diagram в dev-режиме). Подсветку можно задать в адресе:
 * /dev/diagram?assumptions=Task_A,Flow_B&selected=Gateway_C&added=Task_D&readOnly=1
 * `?broken=1` подсовывает повреждённый XML — для проверки onError.
 */

interface DemoSearch {
  assumptions?: string
  selected?: string
  added?: string
  readOnly?: boolean
  broken?: boolean
}

/** События редактора для e2e-проверок (только dev). */
type DemoEvent =
  | { type: 'change'; xml: string }
  | { type: 'import'; warnings: number }
  | { type: 'error'; message: string }
  | { type: 'click'; id: string }
  | { type: 'simulation-start' }

declare global {
  interface Window {
    __diagram?: DiagramEditorHandle
    __diagramEvents?: DemoEvent[]
    __diagramSetXml?: (xml: string) => void
  }
}

/** Подсветка по умолчанию показывает все три маркера на фикстуре техприсоединения. */
const DEMO_HIGHLIGHTS: DiagramHighlights = {
  assumptions: ['Task_SupplementDocs', 'Flow_Supplement_Check'],
  selected: ['Gateway_Power'],
  added: ['Task_SupplyContract'],
}

/** Обрезанный XML: bpmn-js не разберёт его и сообщит об ошибке импорта. */
const BROKEN_XML = '<?xml version="1.0" encoding="UTF-8"?><bpmn:definitions xmlns:bpmn="'

const flag = (value: unknown) => value === true || value === 1 || value === '1'

const ids = (value: string | undefined, fallback: readonly string[]) =>
  value === undefined ? fallback : value.split(',').filter(Boolean)

const record = (event: DemoEvent) => {
  if (!import.meta.env.DEV) return
  window.__diagramEvents ??= []
  window.__diagramEvents.push(event)
}

export const Route = createFileRoute('/dev/diagram')({
  validateSearch: (search: Record<string, unknown>): DemoSearch => ({
    assumptions: typeof search.assumptions === 'string' ? search.assumptions : undefined,
    selected: typeof search.selected === 'string' ? search.selected : undefined,
    added: typeof search.added === 'string' ? search.added : undefined,
    readOnly: flag(search.readOnly),
    broken: flag(search.broken),
  }),
  loader: () =>
    import('@/widgets/diagram-editor/__fixtures__/sample.bpmn?raw').then(
      (module) => module.default,
    ),
  component: DiagramDemo,
})

function DiagramDemo() {
  const sample = Route.useLoaderData()
  const search = Route.useSearch()
  const [xml, setXml] = useState(search.broken ? BROKEN_XML : sample)
  const panelRef = useRef<HTMLElement>(null)
  useEffect(() => {
    if (import.meta.env.DEV) window.__diagramSetXml = setXml
    return () => {
      delete window.__diagramSetXml
    }
  }, [])

  const highlights = useMemo(
    () => ({
      assumptions: ids(search.assumptions, DEMO_HIGHLIGHTS.assumptions),
      selected: ids(search.selected, DEMO_HIGHLIGHTS.selected),
      added: ids(search.added, DEMO_HIGHLIGHTS.added),
    }),
    [search.assumptions, search.selected, search.added],
  )

  const handleReady = useCallback((handle: DiagramEditorHandle) => {
    handle.setPropertiesPanel(panelRef.current)
    if (import.meta.env.DEV) window.__diagram = handle
  }, [])

  const handleChange = useCallback((next: string) => {
    record({ type: 'change', xml: next })
    setXml(next)
  }, [])

  return (
    <main className="flex h-dvh overflow-hidden bg-bg text-fg">
      <LazyDiagramEditor
        xml={xml}
        onChange={handleChange}
        onSimulationStart={() => record({ type: 'simulation-start' })}
        highlights={highlights}
        readOnly={search.readOnly}
        onReady={handleReady}
        onImport={({ warnings }) => record({ type: 'import', warnings: warnings.length })}
        onError={(error) => record({ type: 'error', message: error.message })}
        onElementClick={(id) => record({ type: 'click', id })}
        className="min-w-0 flex-1"
      />
      <aside
        ref={panelRef}
        aria-label="Свойства элемента"
        className="w-80 shrink-0 border-l border-border bg-surface"
      />
    </main>
  )
}
