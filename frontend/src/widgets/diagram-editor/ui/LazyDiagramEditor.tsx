import { lazy, Suspense } from 'react'
import type { LazyDiagramEditorProps } from '../types'

const loadEditor = () => import('./DiagramEditor')

const DiagramEditor = lazy(loadEditor)

/**
 * Начать загрузку чанка редактора заранее — например, в `loader` маршрута рабочего места
 * или при наведении на проект. Повторные вызовы ничего не стоят.
 */
export function preloadDiagramEditor(): Promise<unknown> {
  return loadEditor()
}

/**
 * Редактор BPMN с ленивой загрузкой: bpmn-js, плагины и их стили приходят отдельным чанком.
 * Пока чанк грузится, показывается `fallback` (по умолчанию — пустой блок с тем же `className`,
 * чтобы раскладка не прыгала).
 */
export function LazyDiagramEditor({ fallback, ...props }: LazyDiagramEditorProps) {
  return (
    <Suspense fallback={fallback ?? <div className={props.className} aria-busy="true" />}>
      <DiagramEditor {...props} />
    </Suspense>
  )
}
