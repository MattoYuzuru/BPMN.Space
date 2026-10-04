/**
 * Якоря обучения. Целевые элементы помечаются `data-tour="…"`: так тур и подсказки находят их
 * независимо от текста кнопок. Константы живут в shared, чтобы фичи ставили атрибуты,
 * не импортируя `features/onboarding` (фичи про тур не знают).
 */

/** Атрибут целевого элемента: `<Button {...tourAnchor(TOUR_ANCHORS.projectsNew)} />`. */
export const TOUR_ATTR = 'data-tour'

/**
 * Атрибут слоя обучения (затемнение, карточка, подсказка). Модальные слои дизайн-системы
 * (диалог, меню, поповер, панель) не считают события внутри такого слоя «кликом снаружи».
 */
export const TOUR_LAYER_ATTR = 'data-tour-layer'

export const TOUR_ANCHORS = {
  projectsNew: 'projects.new',
  createSubmit: 'create.submit',
  sourcesAdd: 'sources.add',
  sourceTextContent: 'source-text.content',
  sourceTextSubmit: 'source-text.submit',
  voiceCapture: 'voice.capture',
  runBuild: 'run.build',
  runProgress: 'run.progress',
  questionAnswer: 'question.answer',
  questionIgnore: 'question.ignore',
  answerSubmit: 'answer.submit',
  diagramCanvas: 'diagram.canvas',
  diagramSimulation: 'diagram.simulation',
  headerDownload: 'header.download',
  shareOpen: 'share.open',
  shareCreate: 'share.create',
  shareCopy: 'share.copy',
} as const

export type TourAnchorName = (typeof TOUR_ANCHORS)[keyof typeof TOUR_ANCHORS]

/** Пропсы для элемента-якоря: `{ 'data-tour': name }`. */
export function tourAnchor(name: string): { [TOUR_ATTR]: string } {
  return { [TOUR_ATTR]: name }
}

/**
 * Ссылка на целевой элемент: имя якоря, якорь внутри контейнера (карточка вопроса по
 * `data-question-id`) или произвольный CSS-селектор.
 */
export type AnchorRef = string | { name: string; within?: string } | { selector: string }

/** CSS-селектор элемента по ссылке на якорь. */
export function anchorSelector(ref: AnchorRef): string {
  if (typeof ref === 'string') return `[${TOUR_ATTR}="${ref}"]`
  if ('selector' in ref) return ref.selector
  const own = `[${TOUR_ATTR}="${ref.name}"]`
  return ref.within ? `${ref.within} ${own}` : own
}

/** Событие произошло внутри слоя обучения (карточка, затемнение, подсказка). */
export function isInsideTourLayer(target: EventTarget | null): boolean {
  return target instanceof Element && target.closest(`[${TOUR_LAYER_ATTR}]`) !== null
}

/**
 * Для `onInteractOutside` / `onEscapeKeyDown` модальных слоёв: событие внутри слоя обучения
 * не закрывает окно или меню. Без тура ничего не меняет.
 */
export function guardTourLayer(event: { target: EventTarget | null; preventDefault(): void }) {
  if (isInsideTourLayer(event.target)) event.preventDefault()
}
