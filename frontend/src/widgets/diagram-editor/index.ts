/**
 * Публичный API виджета редактора BPMN. Подробно — docs/frontend/diagram-editor.md.
 *
 * Отсюда нельзя реэкспортировать ничего, что тянет bpmn-js: этот файл входит в стартовый бандл,
 * а редактор грузится отдельным чанком (проверяет `make build`, scripts/check-bundle.mjs).
 */
export type {
  DiagramEditorError,
  DiagramEditorHandle,
  DiagramEditorProps,
  DiagramHighlights,
  DiagramImportResult,
  DiagramImportWarning,
  DiagramSimulation,
  LazyDiagramEditorProps,
  PngBackground,
  PngExportOptions,
  SimulationOption,
} from './types'
export { LazyDiagramEditor, preloadDiagramEditor } from './ui/LazyDiagramEditor'
