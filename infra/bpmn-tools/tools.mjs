import { createRequire } from 'node:module'
import { layoutProcess } from 'bpmn-auto-layout'
import { BpmnModdle } from 'bpmn-moddle'
import { Linter } from 'bpmnlint'
import NodeResolver from 'bpmnlint/lib/resolver/node-resolver.js'

const require = createRequire(import.meta.url)
const resolver = new NodeResolver({ require })
const RULE_TEXT = {
  'conditional-flows': 'Исход условного ветвления не содержит условия или default',
  'end-event-required': 'В процессе нет завершающего события',
  'start-event-required': 'В процессе нет начального события',
  'fake-join': 'Входящие потоки не объединены явным шлюзом',
  'label-required': 'У элемента отсутствует подпись',
  'no-bpmndi': 'Нет координат элемента (BPMN DI)',
  'no-disconnected': 'Элемент не связан с процессом',
  'no-duplicate-sequence-flows': 'Дублируются последовательные потоки',
  'no-gateway-join-fork': 'Разделите слияние и разветвление на два шлюза',
  'no-implicit-split': 'Несколько выходов требуют явного шлюза',
  'no-implicit-end': 'Нет исходящего потока',
  'no-implicit-start': 'Нет входящего потока',
  'single-blank-start-event': 'Несколько альтернативных стартов требуют явного типа события',
  'no-overlapping-elements': 'Элементы схемы пересекаются',
  'superfluous-gateway': 'Шлюз не изменяет движение потока',
  'no-inclusive-gateway': 'Inclusive-шлюз требует дополнительной проверки сценария',
  'no-complex-gateway': 'Complex-шлюз не поддерживается проверяемым поднабором',
}

export async function parse(xml) {
  if (typeof xml !== 'string' || !xml.trim() || /<!DOCTYPE|<!ENTITY|<\?xml-stylesheet/i.test(xml)) {
    throw new Error('XML пуст или содержит запрещённые конструкции')
  }
  const result = await new BpmnModdle().fromXML(xml)
  if (result.warnings.length)
    throw new Error('BPMN XML содержит неподдерживаемые элементы или ссылки')
  return result.rootElement
}

function completeDi(definitions) {
  const processes = definitions.rootElements.filter((e) => e.$type === 'bpmn:Process')
  const ids = processes.flatMap((p) => (p.flowElements || []).map((e) => e.id))
  const represented = new Set(
    (definitions.diagrams || []).flatMap((d) =>
      (d.plane?.planeElement || []).map((e) => e.bpmnElement?.id),
    ),
  )
  return ids.length > 0 && ids.every((id) => represented.has(id))
}

export async function layout(xml) {
  const definitions = await parse(xml)
  // Готовая геометрия не пересчитывается: для пользовательской версии это важный контракт.
  if (completeDi(definitions)) return { xml, warnings: [], engine: 'preserved-di' }
  const result = await layoutProcess(xml)
  const laidOut = await parse(result.xml)
  if (!completeDi(laidOut)) throw new Error('Алгоритм не создал DI для всех узлов и потоков')
  return {
    xml: result.xml,
    warnings: result.warnings.map((w) => `Раскладка: ${String(w.message || w).slice(0, 300)}`),
    engine: 'bpmn-auto-layout@2.0.0-alpha.2',
  }
}

export async function lint(xml) {
  const definitions = await parse(xml)
  const reports = await new Linter({ config: { extends: 'bpmnlint:recommended' }, resolver }).lint(
    definitions,
  )
  return {
    issues: Object.entries(reports).flatMap(([rule, reports]) =>
      reports.map((report) => ({
        rule,
        element_id: report.id || null,
        severity:
          report.category === 'error' || report.category === 'rule-error' ? 'error' : 'warning',
        message: RULE_TEXT[rule] || `Элемент не соответствует правилу «${rule}»`,
      })),
    ),
  }
}
