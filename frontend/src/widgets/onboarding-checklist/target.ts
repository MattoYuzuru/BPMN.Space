import type { ChecklistItemKey, OnboardingTarget, TargetHint } from '@/entities/onboarding'
import { type AnchorRef, TOUR_ANCHORS } from '@/shared/lib/tour-anchors'

/**
 * Куда вести по невыполненному пункту. Сервер говорит, **в какой проект** идти и что нужно
 * (`route`, `hint`), а какой элемент подсветить и что написать — решает фронтенд: якоря и тексты
 * принадлежат интерфейсу, а не данным.
 */

/** Тексты, когда пункт сделать здесь нельзя: сначала нужен предыдущий шаг. */
const NEED_TEXT: Record<Exclude<TargetHint, 'do_item'>, string> = {
  need_project: 'Сначала создайте проект.',
  need_source: 'Добавьте источник — документ, текст или голос.',
  need_diagram: 'Сначала постройте схему.',
  need_questions: 'Запустите сборку — модель задаст вопросы по неясным местам.',
}

/** Что сделать для самого пункта (`hint = do_item`). */
const DO_TEXT: Record<ChecklistItemKey, string> = {
  project_created: 'Нажмите «Новый проект» и создайте первый проект.',
  text_source_added: 'Откройте меню и выберите «Текст»: опишите процесс своими словами.',
  document_uploaded: 'Откройте меню и выберите «Документ»: модель прочитает его как источник.',
  voice_added: 'Откройте меню и выберите «Голосовая заметка»: процесс можно надиктовать.',
  diagram_built: 'Нажмите «Построить схему» — модель прочитает источники и соберёт схему.',
  question_answered: 'Нажмите «Ответить» и напишите ответ — он станет новым источником.',
  assumption_accepted: 'Нажмите «Игнорировать» — модель примет допущение и отметит его на схеме.',
  diagram_rebuilt: 'Нажмите «Построить схему» ещё раз — модель учтёт ваши ответы.',
  diagram_edited: 'Подвигайте или переименуйте любой элемент схемы — правки сохранятся сами.',
  simulation_run: 'Нажмите «Симуляция токена», чтобы увидеть, как процесс идёт по схеме.',
  diagram_exported: 'Откройте «Скачать схему» и выберите формат.',
  project_shared: 'Нажмите «Поделиться» и создайте ссылку на схему.',
}

/** Текст подсказки-указателя по пункту и подсказке сервера. */
export function hintText(item: ChecklistItemKey, hint: TargetHint): string {
  return hint === 'do_item' ? DO_TEXT[item] : NEED_TEXT[hint]
}

/** Якорь самого действия по пункту. */
const DO_ANCHOR: Record<ChecklistItemKey, string> = {
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

/** Якорь подготовительного шага (`need_*`): туда, где его можно сделать. */
const NEED_ANCHOR: Record<Exclude<TargetHint, 'do_item'>, string> = {
  need_project: TOUR_ANCHORS.projectsNew,
  need_source: TOUR_ANCHORS.sourcesAdd,
  need_diagram: TOUR_ANCHORS.runBuild,
  need_questions: TOUR_ANCHORS.runBuild,
}

/** Элемент, на который указать: для вопросов — внутри карточки нужного вопроса. */
export function hintAnchor(
  item: ChecklistItemKey,
  hint: TargetHint,
  questionId?: string | null,
): AnchorRef {
  if (hint !== 'do_item') return NEED_ANCHOR[hint]
  const name = DO_ANCHOR[item]
  if (questionId && (item === 'question_answered' || item === 'assumption_accepted')) {
    return { name, within: `[data-question-id="${questionId}"]` }
  }
  return name
}

/** Панель рабочего места, которую надо раскрыть, чтобы якорь появился на экране. */
export type PanelToExpand = 'sources' | 'questions'

export interface ItemVisit {
  /** Куда перейти: экран проектов или рабочее место проекта (с выбранным вопросом). */
  destination:
    | { to: '/' }
    | { to: '/projects/$projectId'; projectId: string; question: string | undefined }
  anchor: AnchorRef
  text: string
  expand: PanelToExpand | null
  /** Вопрос, который выбрать и показать на схеме (`selectQuestion(id, { focus: true })`). */
  focusQuestionId: string | null
}

/** План визита по ответу сервера: переход, якорь, текст и подготовка экрана. */
export function planItemVisit(item: ChecklistItemKey, target: OnboardingTarget): ItemVisit {
  const questionId = target.question_id ?? null
  const anchor = hintAnchor(item, target.hint, questionId)
  const text = hintText(item, target.hint)
  const name = typeof anchor === 'string' ? anchor : 'name' in anchor ? anchor.name : null
  const destination: ItemVisit['destination'] =
    target.route === 'workspace' && target.project_id
      ? {
          to: '/projects/$projectId',
          projectId: target.project_id,
          question: questionId ?? undefined,
        }
      : { to: '/' }
  const inWorkspace = destination.to !== '/'
  let expand: PanelToExpand | null = null
  if (inWorkspace && name === TOUR_ANCHORS.sourcesAdd) expand = 'sources'
  if (
    inWorkspace &&
    (name === TOUR_ANCHORS.questionAnswer || name === TOUR_ANCHORS.questionIgnore)
  ) {
    expand = 'questions'
  }
  return {
    destination,
    anchor,
    text,
    expand,
    focusQuestionId: inWorkspace && target.hint === 'do_item' ? questionId : null,
  }
}
