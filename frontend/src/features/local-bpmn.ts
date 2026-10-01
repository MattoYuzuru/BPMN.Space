/** Минимальный локальный генератор BPMN для автономного знакомства с редактором. */
export function buildLocalBpmn(title: string, source: string): string {
  const sentences = source
    .replace(/\s+/g, ' ')
    .split(/(?<=[.!?])\s+|,\s*(?:затем|после этого|потом)\s+/i)
    .map((value) =>
      value
        .trim()
        .replace(/^[-\d.)\s]+/, '')
        .replace(/[.!?]+$/, ''),
    )
    .filter((value) => value.length > 10)
    .slice(0, 6)
  const steps = sentences.length > 0 ? sentences : ['Описать и проверить порядок действий']
  const escapeXml = (value: string) =>
    value
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
  const nodes = ['Start', ...steps.map((_, index) => `Task_${index + 1}`), 'End']
  const flows = nodes
    .slice(0, -1)
    .map(
      (id, index) =>
        `<bpmn:sequenceFlow id="Flow_${index + 1}" sourceRef="${id}" targetRef="${nodes[index + 1]}" />`,
    )
    .join('\n')
  const shapes = [
    `<bpmndi:BPMNShape id="Shape_Start" bpmnElement="Start"><dc:Bounds x="160" y="170" width="36" height="36" /></bpmndi:BPMNShape>`,
    ...steps.map(
      (_, index) =>
        `<bpmndi:BPMNShape id="Shape_Task_${index + 1}" bpmnElement="Task_${index + 1}"><dc:Bounds x="${270 + index * 190}" y="148" width="130" height="80" /></bpmndi:BPMNShape>`,
    ),
    `<bpmndi:BPMNShape id="Shape_End" bpmnElement="End"><dc:Bounds x="${300 + steps.length * 190}" y="170" width="36" height="36" /></bpmndi:BPMNShape>`,
    ...nodes
      .slice(0, -1)
      .map(
        (id, index) =>
          `<bpmndi:BPMNEdge id="Edge_Flow_${index + 1}" bpmnElement="Flow_${index + 1}"><di:waypoint x="${id === 'Start' ? 196 : 400 + (index - 1) * 190}" y="${id === 'Start' ? 188 : 188}" /><di:waypoint x="${nodes[index + 1] === 'End' ? 300 + steps.length * 190 : 270 + index * 190}" y="188" /></bpmndi:BPMNEdge>`,
      ),
  ].join('\n')

  return `<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" xmlns:di="http://www.omg.org/spec/DD/20100524/DI" id="Definitions_Local" targetNamespace="http://arkhitektor.local/bpmn" exporter="Архитектор BPMN" exporterVersion="0.2.0">
  <bpmn:process id="Process_Local" name="${escapeXml(title)}" isExecutable="false">
    <bpmn:startEvent id="Start" name="Начало"><bpmn:outgoing>Flow_1</bpmn:outgoing></bpmn:startEvent>
    ${steps.map((step, index) => `<bpmn:task id="Task_${index + 1}" name="${escapeXml(step.slice(0, 72))}"><bpmn:incoming>Flow_${index + 1}</bpmn:incoming><bpmn:outgoing>Flow_${index + 2}</bpmn:outgoing></bpmn:task>`).join('\n    ')}
    <bpmn:endEvent id="End" name="Завершение"><bpmn:incoming>Flow_${steps.length + 1}</bpmn:incoming></bpmn:endEvent>
    ${flows}
  </bpmn:process>
  <bpmndi:BPMNDiagram id="Diagram_Local"><bpmndi:BPMNPlane id="Plane_Local" bpmnElement="Process_Local">${shapes}</bpmndi:BPMNPlane></bpmndi:BPMNDiagram>
</bpmn:definitions>`
}

export interface LocalProject {
  id: string
  title: string
  source: string
  xml: string
  createdAt: string
  demo: true
}

export function saveLocalProject(project: LocalProject) {
  const all: LocalProject[] = JSON.parse(localStorage.getItem('arkhitektor:projects') ?? '[]')
  localStorage.setItem(
    'arkhitektor:projects',
    JSON.stringify([project, ...all.filter((item) => item.id !== project.id)]),
  )
}

export function getLocalProject(id: string): LocalProject | undefined {
  const all: LocalProject[] = JSON.parse(localStorage.getItem('arkhitektor:projects') ?? '[]')
  return all.find((item) => item.id === id)
}
