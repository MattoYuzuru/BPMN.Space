import {
  addedElementIds,
  comparisonBase,
  diagramElements,
  elementTypeLabel,
  upsertVersion,
  type VersionSummary,
  versionKind,
} from './model'

const xml = (extra = '') => `<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
  xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" id="Defs">
  <bpmn:collaboration id="Collab"><bpmn:participant id="Pool" name="ТП" processRef="P" /></bpmn:collaboration>
  <bpmn:process id="P">
    <bpmn:laneSet id="LS"><bpmn:lane id="Lane_A" name="Заявитель" /></bpmn:laneSet>
    <bpmn:startEvent id="Start" name="Нужно
      подключение" />
    <bpmn:task id="Task_A" name="Подать заявку" />
    <bpmn:sequenceFlow id="Flow_1" sourceRef="Start" targetRef="Task_A" />
    ${extra}
  </bpmn:process>
  <bpmndi:BPMNDiagram id="Diagram"><bpmndi:BPMNPlane id="Plane" bpmnElement="Collab" /></bpmndi:BPMNDiagram>
</bpmn:definitions>`

describe('элементы схемы', () => {
  it('читает элементы модели с подписями, без контейнеров и DI', () => {
    const elements = diagramElements(xml())
    expect([...elements.keys()]).toEqual(['Pool', 'Lane_A', 'Start', 'Task_A', 'Flow_1'])
    expect(elements.get('Start')?.name).toBe('Нужно подключение')
    expect(elements.get('Task_A')?.type).toBe('task')
  })

  it('не разбирает один и тот же XML повторно', () => {
    const parse = vi.spyOn(DOMParser.prototype, 'parseFromString')
    const source = xml('<bpmn:task id="Cache_Probe" />')
    const first = diagramElements(source)
    expect(diagramElements(source)).toBe(first)
    expect(parse).toHaveBeenCalledTimes(1)
    parse.mockRestore()
  })

  it('не падает на битом XML', () => {
    expect(diagramElements('<bpmn:definitions').size).toBe(0)
    expect(diagramElements('').size).toBe(0)
  })

  it('находит добавленные узлы и потоки, но не дорожки', () => {
    const next = xml(
      '<bpmn:lane id="Lane_B" /><bpmn:task id="Task_B" name="Оплатить" /><bpmn:sequenceFlow id="Flow_2" sourceRef="Task_A" targetRef="Task_B" />',
    )
    expect(addedElementIds(xml(), next)).toEqual(['Task_B', 'Flow_2'])
  })

  it('замечает изменение связи при сохранённом id потока', () => {
    const before = diagramElements(xml())
    const after = diagramElements(xml().replace('targetRef="Task_A"', 'targetRef="Task_B"'))
    expect(before.get('Flow_1')?.signature).not.toBe(after.get('Flow_1')?.signature)
  })

  it('подписывает типы по-русски', () => {
    expect(elementTypeLabel('exclusiveGateway')).toBe('Шлюз «или»')
    expect(elementTypeLabel('unknownThing')).toBe('Элемент')
  })
})

describe('история версий', () => {
  const item = (
    number: number,
    extra: Partial<Pick<VersionSummary, 'checkpoint' | 'origin'>> = {},
  ): VersionSummary =>
    ({
      id: `v-${number}`,
      number,
      checkpoint: false,
      origin: 'manual',
      ...extra,
    }) as VersionSummary

  it('база сравнения — ближайшая контрольная точка или сборка, иначе предыдущая версия', () => {
    const list = [
      item(6),
      item(5),
      item(4, { checkpoint: true }),
      item(3),
      item(2, { origin: 'generated' }),
    ]
    expect(comparisonBase(list, 6)?.number).toBe(4)
    expect(comparisonBase(list, 4)?.number).toBe(2)
    expect(comparisonBase([item(3), item(2)], 3)?.number).toBe(2)
    expect(comparisonBase([item(1)], 1)).toBeUndefined()
  })

  it('слитая запись с тем же номером заменяет прежнюю и порядок сохраняется', () => {
    const merged = { ...item(3), id: 'v-3b' }
    expect(upsertVersion([item(3), item(2)], merged).map((v) => v.id)).toEqual(['v-3b', 'v-2'])
    expect(upsertVersion([item(2)], item(3)).map((v) => v.number)).toEqual([3, 2])
    expect(upsertVersion([item(3), item(2)], item(3)).map((v) => v.number)).toEqual([3, 2])
  })

  it('вид версии для истории', () => {
    expect(versionKind(item(1, { checkpoint: true }))).toBe('checkpoint')
    expect(versionKind(item(1, { origin: 'generated' }))).toBe('build')
    expect(versionKind(item(1))).toBe('session')
  })
})
