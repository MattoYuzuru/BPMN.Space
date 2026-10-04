import { CHECKLIST_ITEMS, type ChecklistItemKey, type TargetHint } from '@/entities/onboarding'
import { TOUR_ANCHORS } from '@/shared/lib/tour-anchors'
import { hintAnchor, hintText, planItemVisit } from './target'

const HINTS: TargetHint[] = [
  'do_item',
  'need_project',
  'need_source',
  'need_diagram',
  'need_questions',
]

describe('тексты подсказок', () => {
  it('для подготовительных шагов — как в задаче', () => {
    expect(hintText('diagram_edited', 'need_project')).toBe('Сначала создайте проект.')
    expect(hintText('diagram_edited', 'need_source')).toBe(
      'Добавьте источник — документ, текст или голос.',
    )
    expect(hintText('simulation_run', 'need_diagram')).toBe('Сначала постройте схему.')
    expect(hintText('question_answered', 'need_questions')).toBe(
      'Запустите сборку — модель задаст вопросы по неясным местам.',
    )
  })

  it('у каждого пункта есть свой текст действия, не длиннее 160 символов и без восклицаний', () => {
    for (const { key } of CHECKLIST_ITEMS) {
      const text = hintText(key, 'do_item')
      expect(text.length).toBeGreaterThan(10)
      expect(text.length).toBeLessThanOrEqual(160)
      expect(text).not.toContain('!')
    }
    expect(hintText('question_answered', 'do_item')).toBe(
      'Нажмите «Ответить» и напишите ответ — он станет новым источником.',
    )
  })
})

describe('якоря подсказок', () => {
  const DO_ANCHORS: Record<ChecklistItemKey, string> = {
    project_created: TOUR_ANCHORS.projectsNew,
    text_source_added: TOUR_ANCHORS.sourcesAdd,
    document_uploaded: TOUR_ANCHORS.sourcesAdd,
    voice_added: TOUR_ANCHORS.sourcesAdd,
    diagram_built: TOUR_ANCHORS.runBuild,
    question_answered: TOUR_ANCHORS.questionAnswer,
    assumption_accepted: TOUR_ANCHORS.questionIgnore,
    diagram_rebuilt: TOUR_ANCHORS.runBuild,
    diagram_edited: TOUR_ANCHORS.diagramCanvas,
    simulation_run: TOUR_ANCHORS.diagramSimulation,
    diagram_exported: TOUR_ANCHORS.headerDownload,
    project_shared: TOUR_ANCHORS.shareOpen,
  }

  it('каждый из 12 пунктов указывает на свой элемент', () => {
    for (const { key } of CHECKLIST_ITEMS) {
      expect(hintAnchor(key, 'do_item')).toBe(DO_ANCHORS[key])
    }
  })

  it('вопросы подсвечиваются внутри карточки нужного вопроса', () => {
    expect(hintAnchor('question_answered', 'do_item', 'q-7')).toEqual({
      name: TOUR_ANCHORS.questionAnswer,
      within: '[data-question-id="q-7"]',
    })
    expect(hintAnchor('assumption_accepted', 'do_item', 'q-7')).toEqual({
      name: TOUR_ANCHORS.questionIgnore,
      within: '[data-question-id="q-7"]',
    })
    // для других пунктов id вопроса якорь не меняет
    expect(hintAnchor('diagram_built', 'do_item', 'q-7')).toBe(TOUR_ANCHORS.runBuild)
  })

  it('подготовительные шаги ведут к тому, где их можно сделать', () => {
    expect(hintAnchor('project_shared', 'need_project')).toBe(TOUR_ANCHORS.projectsNew)
    expect(hintAnchor('diagram_edited', 'need_source')).toBe(TOUR_ANCHORS.sourcesAdd)
    expect(hintAnchor('diagram_edited', 'need_diagram')).toBe(TOUR_ANCHORS.runBuild)
    expect(hintAnchor('question_answered', 'need_questions')).toBe(TOUR_ANCHORS.runBuild)
  })
})

describe('план визита', () => {
  it('экран проектов: переход на главную, панели не трогаем', () => {
    const visit = planItemVisit('project_created', { route: 'projects', hint: 'do_item' })
    expect(visit.destination).toEqual({ to: '/' })
    expect(visit.anchor).toBe(TOUR_ANCHORS.projectsNew)
    expect(visit.expand).toBeNull()
    expect(visit.focusQuestionId).toBeNull()
  })

  it('«Ответить на вопрос»: рабочее место с ?question=, раскрыть вопросы и показать на схеме', () => {
    const visit = planItemVisit('question_answered', {
      route: 'workspace',
      project_id: 'p1',
      question_id: 'q1',
      hint: 'do_item',
    })
    expect(visit.destination).toEqual({
      to: '/projects/$projectId',
      projectId: 'p1',
      question: 'q1',
    })
    expect(visit.anchor).toEqual({
      name: TOUR_ANCHORS.questionAnswer,
      within: '[data-question-id="q1"]',
    })
    expect(visit.expand).toBe('questions')
    expect(visit.focusQuestionId).toBe('q1')
    expect(visit.text).toContain('Ответить')
  })

  it('«Добавить текст»: раскрыть источники', () => {
    const visit = planItemVisit('text_source_added', {
      route: 'workspace',
      project_id: 'p1',
      hint: 'do_item',
    })
    expect(visit.destination).toEqual({
      to: '/projects/$projectId',
      projectId: 'p1',
      question: undefined,
    })
    expect(visit.anchor).toBe(TOUR_ANCHORS.sourcesAdd)
    expect(visit.expand).toBe('sources')
  })

  it('«Сначала…»: не выбираем вопрос, даже если сервер его назвал', () => {
    const visit = planItemVisit('question_answered', {
      route: 'workspace',
      project_id: 'p1',
      question_id: 'q1',
      hint: 'need_questions',
    })
    expect(visit.anchor).toBe(TOUR_ANCHORS.runBuild)
    expect(visit.focusQuestionId).toBeNull()
    expect(visit.expand).toBeNull()
  })

  it('рабочее место без id проекта — запасной переход на экран проектов', () => {
    const visit = planItemVisit('diagram_edited', { route: 'workspace', hint: 'do_item' })
    expect(visit.destination).toEqual({ to: '/' })
  })

  it('все пункты при любой подсказке дают осмысленный план', () => {
    for (const { key } of CHECKLIST_ITEMS) {
      for (const hint of HINTS) {
        const visit = planItemVisit(key, { route: 'workspace', project_id: 'p', hint })
        expect(visit.text.length).toBeGreaterThan(0)
        expect(visit.anchor).toBeTruthy()
      }
    }
  })
})
