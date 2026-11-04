import type { Schemas } from '@/shared/api/client'
import type { BadgeTone, IconName } from '@/shared/ui'

export type Version = Schemas['Version']
export type VersionDetail = Schemas['VersionDetail']
/** Строка истории: без XML, цитат и отчёта. Полная `Version` подходит и сюда. */
export type VersionSummary = Schemas['VersionSummary']
export type VersionPage = Schemas['VersionPage']
export type VersionOrigin = Schemas['VersionOrigin']
export type VersionDiff = Schemas['VersionDiff']
export type LintIssue = Schemas['LintIssue']

export const VERSION_ORIGIN: Record<
  VersionOrigin,
  { label: string; icon: IconName; tone: BadgeTone }
> = {
  generated: { label: 'Сборка', icon: 'bolt', tone: 'accent' },
  manual: { label: 'Правки', icon: 'pencil', tone: 'neutral' },
}

export function versionLabel(version: Pick<Version, 'number'>): string {
  return `Версия ${version.number}`
}

/** Границы между «осмысленными» версиями: контрольная точка или сборка по источникам. */
export function isMilestone(version: Pick<VersionSummary, 'checkpoint' | 'origin'>): boolean {
  return version.checkpoint || version.origin === 'generated'
}

/**
 * Версия, с которой сравнивают текущую («добавлено в версии»): ближайшая более ранняя контрольная
 * точка или сборка. Если таких в загруженной истории нет — непосредственно предыдущая.
 */
export function comparisonBase<T extends Pick<VersionSummary, 'number' | 'checkpoint' | 'origin'>>(
  list: readonly T[],
  number: number,
): T | undefined {
  const older = list.filter((item) => item.number < number).sort((a, b) => b.number - a.number)
  return older.find(isMilestone) ?? older[0]
}

/** В загруженной истории есть контрольная точка или сборка раньше `number` (база уже определена). */
export function hasMilestoneBefore<
  T extends Pick<VersionSummary, 'number' | 'checkpoint' | 'origin'>,
>(list: readonly T[], number: number): boolean {
  return list.some((item) => item.number < number && isMilestone(item))
}

/** Вставляет сохранённую версию в список истории: тот же номер (слитая сессия) заменяется. */
export function upsertVersion<T extends Pick<VersionSummary, 'id' | 'number'>>(
  list: readonly T[],
  version: T,
): T[] {
  return [
    version,
    ...list.filter((item) => item.id !== version.id && item.number !== version.number),
  ].sort((a, b) => b.number - a.number)
}

/** Лёгкая запись для списков: без отчёта, цитат и дорожек. */
export function toSummary(version: VersionSummary): VersionSummary {
  const { id, project_id, number, origin, created_at, run_id, actor_email, diff } = version
  return {
    id,
    project_id,
    number,
    origin,
    created_at,
    run_id,
    actor_email,
    diff,
    lint_count: version.lint_count,
    assumption_count: version.assumption_count,
    label: version.label,
    checkpoint: version.checkpoint,
    session_started_at: version.session_started_at,
    updated_at: version.updated_at,
    saved_count: version.saved_count,
  }
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
const ELEMENTS_CACHE_SIZE = 4
const elementsCache = new Map<string, Map<string, DiagramElement>>()

/**
 * Элементы схемы по id. Разбор XML идёт в главном потоке, поэтому результат запоминается:
 * несколько последних XML (текущий и база сравнения) повторно не парсятся. Возвращённую карту
 * менять нельзя.
 */
export function diagramElements(xml: string): Map<string, DiagramElement> {
  if (!xml) return new Map()
  const cached = elementsCache.get(xml)
  if (cached) {
    // Свежие записи — в конец, вытесняется самая давняя.
    elementsCache.delete(xml)
    elementsCache.set(xml, cached)
    return cached
  }
  const parsed = parseDiagramElements(xml)
  elementsCache.set(xml, parsed)
  if (elementsCache.size > ELEMENTS_CACHE_SIZE) {
    const oldest = elementsCache.keys().next().value
    if (oldest !== undefined) elementsCache.delete(oldest)
  }
  return parsed
}

function parseDiagramElements(xml: string): Map<string, DiagramElement> {
  const result = new Map<string, DiagramElement>()
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

export type VersionKind = 'checkpoint' | 'session' | 'build'

/** Как показать версию в истории: именованная точка, сессия правок или сборка по источникам. */
export function versionKind(version: Pick<VersionSummary, 'checkpoint' | 'origin'>): VersionKind {
  if (version.checkpoint) return 'checkpoint'
  return version.origin === 'generated' ? 'build' : 'session'
}
