// Плагины bpmn.io без собственных типов. Описываем только то, что использует виджет.

declare module 'bpmn-js-token-simulation' {
  const TokenSimulationModule: Record<string, unknown>
  export default TokenSimulationModule
}

declare module 'diagram-js-minimap' {
  const MinimapModule: Record<string, unknown>
  export default MinimapModule
}

declare module 'bpmn-js-properties-panel' {
  export const BpmnPropertiesPanelModule: Record<string, unknown>
  export const BpmnPropertiesProviderModule: Record<string, unknown>
}
