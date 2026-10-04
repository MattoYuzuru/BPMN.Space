import type { Schemas } from '@/shared/api/client'

export type ChecklistItemKey = Schemas['ChecklistItem']
export type TourStepKey = Schemas['TourStepKey']
export type TourStatus = Schemas['TourStatus']

export type ChecklistGroupKey = 'sources' | 'analysis' | 'diagram' | 'team'

export interface ChecklistGroup {
  key: ChecklistGroupKey
  title: string
}

/** Четыре группы чек-листа «Начало работы» в порядке показа. */
export const CHECKLIST_GROUPS: readonly ChecklistGroup[] = [
  { key: 'sources', title: 'Источники' },
  { key: 'analysis', title: 'Анализ' },
  { key: 'diagram', title: 'Схема' },
  { key: 'team', title: 'Команда' },
]

export interface ChecklistItemMeta {
  key: ChecklistItemKey
  title: string
  group: ChecklistGroupKey
}

/**
 * Название и группа каждого пункта. `Record` по ключам контракта API: пункт, добавленный на
 * сервере, но не описанный здесь, не даст собраться проекту.
 */
const META: Record<ChecklistItemKey, Omit<ChecklistItemMeta, 'key'>> = {
  project_created: { title: 'Создать проект', group: 'sources' },
  text_source_added: { title: 'Добавить текст', group: 'sources' },
  document_uploaded: { title: 'Загрузить документ', group: 'sources' },
  voice_added: { title: 'Добавить голосовую заметку', group: 'sources' },
  diagram_built: { title: 'Получить первую схему', group: 'analysis' },
  question_answered: { title: 'Ответить на вопрос', group: 'analysis' },
  assumption_accepted: { title: 'Принять допущение', group: 'analysis' },
  diagram_rebuilt: { title: 'Перестроить с учётом ответов', group: 'analysis' },
  diagram_edited: { title: 'Изменить схему вручную', group: 'diagram' },
  simulation_run: { title: 'Запустить симуляцию токена', group: 'diagram' },
  diagram_exported: { title: 'Скачать схему', group: 'diagram' },
  project_shared: { title: 'Поделиться проектом', group: 'team' },
}

/** Порядок показа пунктов (внутри группы — как здесь). */
const ORDER: readonly ChecklistItemKey[] = [
  'project_created',
  'text_source_added',
  'document_uploaded',
  'voice_added',
  'diagram_built',
  'question_answered',
  'assumption_accepted',
  'diagram_rebuilt',
  'diagram_edited',
  'simulation_run',
  'diagram_exported',
  'project_shared',
]

/** 12 пунктов чек-листа в порядке показа. */
export const CHECKLIST_ITEMS: readonly ChecklistItemMeta[] = ORDER.map((key) => ({
  key,
  ...META[key],
}))

/** Сколько пунктов в чек-листе. */
export const CHECKLIST_TOTAL = CHECKLIST_ITEMS.length

export function checklistItem(key: ChecklistItemKey): ChecklistItemMeta {
  return { key, ...META[key] }
}

/** Название пункта для уведомления и списка. */
export const checklistItemTitle = (key: ChecklistItemKey): string => META[key].title

/** Пункты, которые клиент сообщает сам: сервер симуляцию и скачивание не видит. */
export const CLIENT_REPORTABLE_ITEMS: readonly ChecklistItemKey[] = [
  'simulation_run',
  'diagram_exported',
]

export interface ChecklistGroupView extends ChecklistGroup {
  items: ChecklistItemMeta[]
}

/** Пункты по группам в порядке показа. */
export function groupedChecklistItems(): ChecklistGroupView[] {
  return CHECKLIST_GROUPS.map((group) => ({
    ...group,
    items: CHECKLIST_ITEMS.filter((item) => item.group === group.key),
  }))
}
