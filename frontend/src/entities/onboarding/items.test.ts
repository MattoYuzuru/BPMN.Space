import {
  CHECKLIST_GROUPS,
  CHECKLIST_ITEMS,
  CHECKLIST_TOTAL,
  CLIENT_REPORTABLE_ITEMS,
  checklistItem,
  checklistItemTitle,
  groupedChecklistItems,
} from './items'

describe('пункты чек-листа', () => {
  it('их двенадцать, ключи не повторяются', () => {
    expect(CHECKLIST_TOTAL).toBe(12)
    expect(new Set(CHECKLIST_ITEMS.map((item) => item.key)).size).toBe(12)
  })

  it('порядок, названия и группы — как в эпике', () => {
    expect(CHECKLIST_ITEMS.map((item) => [item.key, item.title, item.group])).toEqual([
      ['project_created', 'Создать проект', 'sources'],
      ['text_source_added', 'Добавить текст', 'sources'],
      ['document_uploaded', 'Загрузить документ', 'sources'],
      ['voice_added', 'Добавить голосовую заметку', 'sources'],
      ['diagram_built', 'Получить первую схему', 'analysis'],
      ['question_answered', 'Ответить на вопрос', 'analysis'],
      ['assumption_accepted', 'Принять допущение', 'analysis'],
      ['diagram_rebuilt', 'Перестроить с учётом ответов', 'analysis'],
      ['diagram_edited', 'Изменить схему вручную', 'diagram'],
      ['simulation_run', 'Запустить таймлайн процесса', 'diagram'],
      ['diagram_exported', 'Скачать схему', 'diagram'],
      ['project_shared', 'Поделиться проектом', 'team'],
    ])
  })

  it('группы идут в порядке показа и содержат пункты по порядку', () => {
    expect(CHECKLIST_GROUPS.map((group) => group.title)).toEqual([
      'Источники',
      'Анализ',
      'Схема',
      'Команда',
    ])
    const grouped = groupedChecklistItems()
    expect(grouped.map((group) => group.items.length)).toEqual([4, 4, 3, 1])
    expect(grouped.flatMap((group) => group.items)).toEqual([...CHECKLIST_ITEMS])
  })

  it('метаданные по ключу', () => {
    expect(checklistItem('project_shared')).toEqual({
      key: 'project_shared',
      title: 'Поделиться проектом',
      group: 'team',
    })
    expect(checklistItemTitle('diagram_exported')).toBe('Скачать схему')
  })

  it('клиент сообщает только симуляцию и скачивание', () => {
    expect([...CLIENT_REPORTABLE_ITEMS].sort()).toEqual(['diagram_exported', 'simulation_run'])
  })
})
