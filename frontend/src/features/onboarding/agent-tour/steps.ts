import { TOUR_ANCHORS } from '@/shared/lib/tour-anchors'
import type { TourStep } from '../tour/types'
import { AGENT_COPY } from './copy'

/** Что тур знает о настройках: сколько токенов уже есть (ветка «уже подключён»). */
export interface AgentTourContext {
  tokenCount: number
}

/** Ключи шагов: клиентский сценарий, с бэкендовым `TourStepKey` не связан. */
export const AGENT_TOUR_STEP_KEYS = [
  'agent.tools',
  'agent.tokens',
  'agent.create-token',
  'agent.copy-command',
  'agent.review',
] as const

export type AgentTourStepKey = (typeof AGENT_TOUR_STEP_KEYS)[number]

/** Пока учим только настройкам: экран один, поэтому все шаги привязаны к `/settings`. */
const settings = () => ({ to: '/settings' })

/** Сценарий из пяти шагов: инструменты, доступ, токен, команда, проверка коллегой. */
export const agentTourSteps: TourStep<AgentTourContext>[] = [
  {
    key: 'agent.tools',
    chapter: 'agent',
    title: AGENT_COPY.tools.title,
    kind: 'story',
    route: settings,
    anchor: TOUR_ANCHORS.settingsTools,
    side: 'bottom',
    align: 'start',
    pages: [
      { text: AGENT_COPY.tools.intro },
      {
        text: AGENT_COPY.tools.addKey,
        anchor: TOUR_ANCHORS.toolsAddKey,
        side: 'left',
        align: 'end',
      },
    ],
  },
  {
    key: 'agent.tokens',
    chapter: 'agent',
    title: AGENT_COPY.tokens.title,
    kind: 'story',
    route: settings,
    anchor: TOUR_ANCHORS.agentTokens,
    side: 'left',
    align: 'start',
    pages: [{ text: AGENT_COPY.tokens.text }],
    view: ({ ctx }) =>
      ctx.tokenCount > 0 ? { pages: [{ text: AGENT_COPY.tokens.existing }] } : undefined,
  },
  {
    key: 'agent.create-token',
    chapter: 'agent',
    title: AGENT_COPY.create.title,
    kind: 'action',
    route: settings,
    anchor: TOUR_ANCHORS.agentCreateToken,
    side: 'left',
    align: 'end',
    pages: [{ text: AGENT_COPY.create.text }],
    until: (signal) => signal.type === 'agent.token.created',
  },
  {
    key: 'agent.copy-command',
    chapter: 'agent',
    title: AGENT_COPY.command.title,
    kind: 'action',
    route: settings,
    anchor: TOUR_ANCHORS.agentCopyCommand,
    side: 'left',
    align: 'start',
    pages: [{ text: AGENT_COPY.command.text }],
    // Окно могли закрыть, не скопировав команду: шаг не должен запирать экран.
    optional: true,
    until: (signal) => signal.type === 'agent.command.copied',
  },
  {
    key: 'agent.review',
    chapter: 'review',
    title: AGENT_COPY.review.title,
    kind: 'finish',
    pages: [{ text: AGENT_COPY.review.text }],
    actions: [
      {
        id: 'again',
        label: 'Пройти снова',
        variant: 'ghost',
        run: (api) => api.goto('agent.tools'),
      },
      {
        id: 'done',
        label: 'Готово',
        variant: 'primary',
        run: (api) => api.finish('completed'),
      },
    ],
  },
]

/** Первый шаг сценария; с него начинается тур и на него ведёт «Пройти снова». */
export const FIRST_AGENT_STEP = 'agent.tools'
