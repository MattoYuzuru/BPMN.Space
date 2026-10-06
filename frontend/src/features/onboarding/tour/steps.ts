import { TOUR_ANCHORS, TOUR_ATTR } from '@/shared/lib/tour-anchors'
import type { TourContext } from './context'
import { COPY } from './copy'
import type { RouteTarget, StepAction, StepView, TourApi, TourStep } from './types'

/** Ключи шагов — те же, что знает бэкенд (`TourStepKey`). */
export const STEP_KEYS = [
  'project.create',
  'sources.sample',
  'sources.text',
  'sources.voice',
  'run.start',
  'run.wait',
  'question.answer',
  'question.ignore',
  'diagram.tour',
  'share.create',
  'finish',
] as const

export type TourStepKey = (typeof STEP_KEYS)[number]

/** Клиентский таймаут ожидания прогона (серверный дедлайн — 600 с). */
export const RUN_SLOW_MS = 60_000
export const RUN_GIVE_UP_MS = 150_000

const SKIP: StepAction = {
  id: 'skip',
  label: 'Пропустить шаг',
  variant: 'ghost',
  run: (api) => api.skipStep(),
}

/** Экран рабочего места учебного проекта; пока проекта нет — шаг не привязан к маршруту. */
function workspace(ctx: TourContext): RouteTarget | undefined {
  return ctx.projectId
    ? { to: '/projects/$projectId', params: { projectId: ctx.projectId } }
    : undefined
}

/** Элемент-якорь внутри карточки вопроса; несколько имён — «любой из них» (кнопка меняется по ходу). */
function inQuestion(id: string, ...names: string[]) {
  return {
    selector: names.map((name) => `[data-question-id="${id}"] [${TOUR_ATTR}="${name}"]`).join(', '),
  }
}

/** Прогон завершён, открытых вопросов нет. */
const finishedWithoutQuestions = (ctx: TourContext) =>
  ctx.result !== null && ctx.result.openQuestions === 0

/** Вопрос шага 8: открытый, не тот, что подсвечивали в шаге 7. */
const ignoreTarget = (ctx: TourContext) => ctx.openQuestionIds.find((id) => id !== ctx.pickedId)

/** Прогон упал, и вопросов нет: продолжать тур нечем. */
const failedEmpty = (ctx: TourContext) =>
  ctx.result !== null && ctx.result.status !== 'succeeded' && ctx.result.openQuestions === 0

/** Свежий прогон на секунду-другую «в очереди», даже когда место свободно: очередь называем после паузы. */
const QUEUED_NOTICE_MS = 3000

function runStageText(ctx: TourContext, elapsedMs: number): string {
  if (ctx.queued && elapsedMs >= QUEUED_NOTICE_MS) return COPY.run.queued
  switch (ctx.stage) {
    case 'extracting':
    case 'reconciling':
      return COPY.run.extracting
    case 'structuring':
    case 'validating':
    case 'layout':
      return COPY.run.structuring
    default:
      return COPY.run.reading
  }
}

const skipChapter: StepAction = {
  id: 'skip-chapter',
  label: COPY.run.skipChapter,
  variant: 'ghost',
  run: (api: TourApi) => api.goto('share.create'),
}

const baseSteps: TourStep<TourContext>[] = [
  {
    key: 'project.create',
    chapter: 'sources',
    title: COPY.create.title,
    kind: 'action',
    route: () => ({ to: '/', alt: [{ to: '/projects' }] }),
    anchor: (ctx) =>
      ctx.present.createSubmit ? TOUR_ANCHORS.createSubmit : TOUR_ANCHORS.projectsNew,
    side: 'bottom',
    pages: [{ text: COPY.create.text }],
    prepare: (ctx) => {
      ctx.ui.interceptCreate(() => ctx.firstTitle)
      return () => ctx.ui.interceptCreate(null)
    },
    until: (signal) => signal.type === 'project.created',
  },
  {
    key: 'sources.sample',
    chapter: 'sources',
    title: COPY.sample.title,
    kind: 'action',
    route: workspace,
    anchor: TOUR_ANCHORS.sourcesAdd,
    side: 'right',
    align: 'start',
    pages: [{ text: COPY.sample.intro }, { text: COPY.sample.pick }],
    prepare: (ctx) => {
      ctx.ui.expandPanel('sources')
      return undefined
    },
    // Первая страница листается «Далее»; на второй пользователь сам выбирает пример в меню.
    view: ({ page }) =>
      page === 0
        ? {
            actions: [
              {
                id: 'next',
                label: COPY.sample.next,
                variant: 'primary',
                run: (api) => api.next(),
              },
              SKIP,
            ],
          }
        : undefined,
    until: (signal) => signal.type === 'source.added',
  },
  {
    key: 'sources.text',
    chapter: 'sources',
    title: COPY.text.title,
    kind: 'action',
    route: workspace,
    anchor: (ctx) =>
      ctx.present.textContent ? TOUR_ANCHORS.sourceTextContent : TOUR_ANCHORS.sourcesAdd,
    side: 'right',
    align: 'start',
    pages: [{ text: COPY.text.suggested }],
    view: ({ ctx }) => ({
      pages: [
        {
          text: ctx.present.textContent
            ? ctx.textSuggestion
              ? COPY.text.suggested
              : COPY.text.plain
            : COPY.text.open,
        },
      ],
    }),
    prepare: (ctx) => {
      ctx.ui.expandPanel('sources')
      ctx.ui.setTextSuggestion(ctx.textSuggestion)
      return () => ctx.ui.setTextSuggestion(null)
    },
    until: (signal) => signal.type === 'source.added' && signal.kind === 'text',
  },
  {
    key: 'sources.voice',
    chapter: 'sources',
    title: COPY.voice.title,
    kind: 'action',
    route: workspace,
    anchor: (ctx) =>
      ctx.present.voiceCapture ? TOUR_ANCHORS.voiceCapture : TOUR_ANCHORS.sourcesAdd,
    side: 'right',
    align: 'start',
    pages: [{ text: COPY.voice.open }],
    prepare: (ctx) => {
      ctx.ui.expandPanel('sources')
      return undefined
    },
    view: ({ seen }) =>
      seen['voice.permission-denied'] || seen['voice.unavailable']
        ? {
            pages: [{ text: COPY.voice.blocked }],
            actions: [{ ...SKIP, variant: 'primary' }],
          }
        : undefined,
    until: (signal) => signal.type === 'source.added' && signal.kind === 'voice',
  },
  {
    key: 'run.start',
    chapter: 'questions',
    title: COPY.build.title,
    kind: 'action',
    route: workspace,
    anchor: TOUR_ANCHORS.runBuild,
    side: 'bottom',
    pages: [{ text: COPY.build.text }],
    // «Пропустить шаг» тут вёл бы в ожидание несуществующего прогона: пропускаем главу целиком.
    actions: [skipChapter],
    // Диалоги источников закрываем: за ними кнопки шапки не достать.
    prepare: (ctx) => {
      ctx.ui.closeDialogs()
      return undefined
    },
    view: ({ ctx }): StepView | undefined => {
      if (ctx.processing > 0) {
        return { tone: 'waiting', pages: [{ text: COPY.build.waiting }], anchor: null }
      }
      if (ctx.loaded && ctx.sources === 0) {
        return {
          pages: [{ text: COPY.build.noSources }],
          anchor: TOUR_ANCHORS.sourcesAdd,
          side: 'right',
          align: 'start',
        }
      }
      return undefined
    },
    // Прогон уже идёт (нажали раньше или вернулись на шаг): сразу к ожиданию.
    doneWhen: (ctx) => ctx.runActive,
    until: (signal) => signal.type === 'run.started',
  },
  {
    key: 'run.wait',
    chapter: 'questions',
    title: COPY.run.title,
    kind: 'wait',
    route: workspace,
    anchor: TOUR_ANCHORS.runProgress,
    side: 'bottom',
    pages: [{ text: COPY.run.reading }],
    ticks: [QUEUED_NOTICE_MS, RUN_SLOW_MS, RUN_GIVE_UP_MS],
    view: ({ ctx, elapsedMs }): StepView => {
      if (failedEmpty(ctx)) {
        return {
          tone: 'error',
          title: COPY.run.failedTitle,
          pages: [{ text: COPY.run.failed }],
          anchor: null,
          actions: [
            {
              id: 'retry',
              label: COPY.run.retry,
              variant: 'primary',
              run: (api) => {
                ctx.ops.retryRun()
                api.goto('run.wait')
              },
            },
            skipChapter,
          ],
        }
      }
      if (finishedWithoutQuestions(ctx)) {
        return {
          title: COPY.run.noQuestionsTitle,
          pages: [{ text: COPY.run.noQuestions }],
          anchor: null,
          actions: [
            { id: 'next', label: COPY.run.next, variant: 'primary', run: (api) => api.next() },
          ],
        }
      }
      const queuedText = ctx.queued && elapsedMs >= QUEUED_NOTICE_MS
      const text = queuedText
        ? COPY.run.queued
        : elapsedMs >= RUN_SLOW_MS
          ? COPY.run.slow
          : runStageText(ctx, elapsedMs)
      return {
        tone: 'waiting',
        pages: [{ text }],
        actions: elapsedMs >= RUN_GIVE_UP_MS ? [skipChapter] : undefined,
      }
    },
    // Вопросы есть (в том числе у упавшего прогона): идём к ним; пустые итоги разбирает `view`.
    until: (signal) => signal.type === 'run.finished' && signal.openQuestions > 0,
    doneWhen: (ctx) => ctx.result !== null && ctx.result.openQuestions > 0,
  },
  {
    key: 'question.answer',
    chapter: 'questions',
    title: COPY.answer.title,
    kind: 'action',
    route: workspace,
    anchor: (ctx) => {
      const id = ctx.pickedId ?? ctx.openQuestionIds[0]
      return id
        ? inQuestion(id, TOUR_ANCHORS.answerComposer, TOUR_ANCHORS.questionAnswer)
        : undefined
    },
    // Карточка стоит у вопроса; вырез освобождает всю форму: ввод, микрофон и отправку.
    cardAnchor: (ctx) => {
      const id = ctx.pickedId ?? ctx.openQuestionIds[0]
      return id ? { selector: `[data-question-id="${id}"]` } : undefined
    },
    side: 'left',
    align: 'start',
    pages: [{ text: COPY.answer.text }],
    prepare: (ctx) => {
      ctx.ui.expandPanel('questions')
      ctx.ui.showOpenQuestions()
      return undefined
    },
    skipIf: finishedWithoutQuestions,
    until: (signal) => signal.type === 'question.answered',
  },
  {
    key: 'question.ignore',
    chapter: 'questions',
    title: COPY.ignore.title,
    kind: 'action',
    route: workspace,
    anchor: (ctx) => {
      const id = ignoreTarget(ctx)
      return id ? inQuestion(id, TOUR_ANCHORS.questionIgnore) : undefined
    },
    cardAnchor: (ctx) => {
      const id = ignoreTarget(ctx)
      return id ? { selector: `[data-question-id="${id}"]` } : undefined
    },
    side: 'left',
    align: 'start',
    pages: [{ text: COPY.ignore.text }],
    prepare: (ctx) => {
      ctx.ui.expandPanel('questions')
      ctx.ui.showOpenQuestions()
      return undefined
    },
    // Вопрос был один (или ни одного): игнорировать нечего.
    skipIf: (ctx) => ctx.result !== null && ctx.result.openQuestions < 2,
    until: (signal) => signal.type === 'question.ignored',
  },
  {
    key: 'diagram.tour',
    chapter: 'diagram',
    title: COPY.diagram.title,
    kind: 'story',
    route: workspace,
    anchor: TOUR_ANCHORS.diagramCanvas,
    side: 'right',
    pages: [
      { text: COPY.diagram.canvas, anchor: TOUR_ANCHORS.diagramCanvas, allowOutside: true },
      {
        text: COPY.diagram.simulation,
        anchor: TOUR_ANCHORS.diagramCanvas,
        cardAnchor: TOUR_ANCHORS.diagramSimulation,
        side: 'bottom',
        allowOutside: true,
      },
      { text: COPY.diagram.download, anchor: TOUR_ANCHORS.headerDownload, side: 'bottom' },
    ],
    // Схемы нет, если прогон упал: показывать нечего.
    skipIf: (ctx) =>
      ctx.result !== null && (ctx.result.status !== 'succeeded' || !ctx.result.hasDiagram),
  },
  {
    key: 'share.create',
    chapter: 'diagram',
    title: COPY.share.title,
    kind: 'action',
    route: workspace,
    anchor: (ctx) => {
      if (ctx.shareCreated) return TOUR_ANCHORS.shareCopy
      return ctx.present.shareCreate ? TOUR_ANCHORS.shareCreate : TOUR_ANCHORS.shareOpen
    },
    side: 'bottom',
    pages: [{ text: COPY.share.text }],
    view: ({ ctx }): StepView | undefined =>
      ctx.shareCreated
        ? {
            pages: [{ text: COPY.share.created }],
            actions: [
              {
                id: 'next',
                label: COPY.share.next,
                variant: 'primary',
                // Ссылку уже скопировали или не хотят: закрываем окно, чтобы финал не лёг на него.
                run: (api) => {
                  ctx.ui.closeShareDialog()
                  api.next()
                },
              },
            ],
          }
        : undefined,
    // Ссылка создана и окно закрыто — дальше сами; раньше можно нажать «Дальше».
    doneWhen: (ctx) => ctx.shareCreated && !ctx.present.shareCreate && !ctx.present.shareCopy,
  },
  {
    key: 'finish',
    chapter: null,
    title: COPY.finish.title,
    kind: 'finish',
    pages: [{ text: COPY.finish.text }],
    view: ({ ctx }) => ({
      actions: [
        {
          id: 'open-checklist',
          label: COPY.finish.openChecklist,
          variant: 'primary',
          run: (api) => {
            api.finish('completed')
            ctx.ui.openChecklist()
          },
        },
        {
          id: 'done',
          label: COPY.finish.done,
          variant: 'ghost',
          run: (api) => api.finish('completed'),
        },
      ],
    }),
  },
]

/** Учебный проект удалён: любой шаг после создания предлагает начать заново или завершить. */
function withDeletedGuard(step: TourStep<TourContext>): TourStep<TourContext> {
  if (step.key === 'project.create' || step.kind === 'finish') return step
  return {
    ...step,
    route: (ctx) => (ctx.deleted ? undefined : step.route?.(ctx)),
    skipIf: step.skipIf ? (ctx) => !ctx.deleted && step.skipIf?.(ctx) === true : undefined,
    doneWhen: step.doneWhen ? (ctx) => !ctx.deleted && step.doneWhen?.(ctx) === true : undefined,
    view: (view) =>
      view.ctx.deleted
        ? {
            tone: 'error',
            title: COPY.deleted.title,
            pages: [{ text: COPY.deleted.text }],
            anchor: null,
            actions: [
              {
                id: 'restart',
                label: COPY.deleted.restart,
                variant: 'primary',
                run: (api) => {
                  view.ctx.ops
                    .restart()
                    .then(() => api.goto('project.create'))
                    .catch(() => undefined)
                },
              },
              {
                id: 'end',
                label: COPY.deleted.end,
                variant: 'ghost',
                run: (api) => api.finish('dismissed'),
              },
            ],
          }
        : step.view?.(view),
  }
}

/** Сценарий тура: 11 шагов трёх глав и финал. */
export const tourSteps: TourStep<TourContext>[] = baseSteps.map(withDeletedGuard)
