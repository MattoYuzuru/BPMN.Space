import type { Schemas } from '@/shared/api/client'
import type { BadgeTone, IconName } from '@/shared/ui'

export type Version = Schemas['Version']
export type VersionDetail = Schemas['VersionDetail']
export type VersionOrigin = Schemas['VersionOrigin']
export type VersionDiff = Schemas['VersionDiff']
export type LintIssue = Schemas['LintIssue']

export const VERSION_ORIGIN: Record<
  VersionOrigin,
  { label: string; icon: IconName; tone: BadgeTone }
> = {
  generated: { label: 'Построена', icon: 'bolt', tone: 'accent' },
  manual: { label: 'Правка вручную', icon: 'pencil', tone: 'neutral' },
}

export function versionLabel(version: Pick<Version, 'number'>): string {
  return `Версия ${version.number}`
}

export function hasDiff(diff: VersionDiff): boolean {
  return diff.added + diff.removed + diff.changed > 0
}

const BPMN_MODEL = 'http://www.omg.org/spec/BPMN/20100524/MODEL'
/** Контейнеры, а не элементы схемы: их не подсвечиваем и не считаем в диффе. */
const CONTAINERS = new Set([
  'definitions',
  'process',
  'collaboration',
  'laneSet',
  'extensionElements',
  'documentation',
])

export interface DiagramElement {
  id: string
  type: string
  name: string
  /** Атрибуты и вложенные условия BPMN, без графических координат DI. */
  signature: string
}

/** Элементы модели BPMN (задачи, события, шлюзы, дорожки, потоки) с подписями. */
export function diagramElements(xml: string): Map<string, DiagramElement> {
  const result = new Map<string, DiagramElement>()
  if (!xml) return result
  const doc = new DOMParser().parseFromString(xml, 'application/xml')
  if (doc.getElementsByTagName('parsererror').length > 0) return result
  for (const element of Array.from(doc.getElementsByTagNameNS(BPMN_MODEL, '*'))) {
    const id = element.getAttribute('id')
    if (!id || CONTAINERS.has(element.localName)) continue
    result.set(id, {
      id,
      type: element.localName,
      name: (element.getAttribute('name') ?? '').replace(/\s+/g, ' ').trim(),
      signature: [
        element.localName,
        ...Array.from(element.attributes)
          .filter((attribute) => attribute.name !== 'id' && !attribute.name.startsWith('xmlns'))
          .map((attribute) => `${attribute.name}=${attribute.value.trim()}`)
          .sort(),
        element.textContent?.replace(/\s+/g, ' ').trim() ?? '',
      ].join('|'),
    })
  }
  return result
}

/** Контейнеры (пул, дорожки) не подсвечиваем: заливка целой дорожки перекрывает схему. */
const NOT_MARKED = new Set(['participant', 'lane', 'textAnnotation', 'association', 'messageFlow'])

/** id элементов, которых не было в предыдущей версии, — маркер «добавлено» на схеме. */
export function addedElementIds(previousXml: string, xml: string): string[] {
  const before = diagramElements(previousXml)
  return [...diagramElements(xml).values()]
    .filter((element) => !before.has(element.id) && !NOT_MARKED.has(element.type))
    .map((element) => element.id)
}

const TYPE_LABEL: Record<string, string> = {
  task: 'Задача',
  userTask: 'Задача',
  serviceTask: 'Сервисная задача',
  sendTask: 'Отправка',
  receiveTask: 'Получение',
  manualTask: 'Ручная задача',
  businessRuleTask: 'Бизнес-правило',
  scriptTask: 'Скрипт',
  subProcess: 'Подпроцесс',
  callActivity: 'Вызов процесса',
  startEvent: 'Начальное событие',
  endEvent: 'Конечное событие',
  intermediateThrowEvent: 'Промежуточное событие',
  intermediateCatchEvent: 'Промежуточное событие',
  boundaryEvent: 'Граничное событие',
  exclusiveGateway: 'Шлюз «или»',
  parallelGateway: 'Шлюз «и»',
  inclusiveGateway: 'Включающий шлюз',
  eventBasedGateway: 'Шлюз по событию',
  sequenceFlow: 'Поток',
  messageFlow: 'Поток сообщений',
  lane: 'Дорожка',
  participant: 'Участник',
  dataObjectReference: 'Объект данных',
  dataStoreReference: 'Хранилище данных',
  textAnnotation: 'Примечание',
}

export function elementTypeLabel(type: string): string {
  return TYPE_LABEL[type] ?? 'Элемент'
}
