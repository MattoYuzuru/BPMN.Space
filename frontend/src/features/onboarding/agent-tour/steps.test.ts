import type { OnboardingSignal } from '@/shared/lib/onboarding-signals'
import { TOUR_ANCHORS } from '@/shared/lib/tour-anchors'
import { resolveView } from '../tour/machine'
import type { TourStep } from '../tour/types'
import {
  AGENT_TOUR_STEP_KEYS,
  type AgentTourContext,
  agentTourSteps,
  FIRST_AGENT_STEP,
} from './steps'

const step = (key: string): TourStep<AgentTourContext> => {
  const found = agentTourSteps.find((item) => item.key === key)
  if (!found) throw new Error(`нет шага ${key}`)
  return found
}

const ctx: AgentTourContext = { tokenCount: 0 }

function viewOf(key: string, patch: Partial<AgentTourContext> = {}, page = 0) {
  return resolveView(step(key), { ctx: { ...ctx, ...patch }, elapsedMs: 0, seen: {}, page })
}

describe('агентский тур', () => {
  it('пять шагов: инструменты, доступ, токен, команда, проверка', () => {
    expect(agentTourSteps.map((item) => item.key)).toEqual([...AGENT_TOUR_STEP_KEYS])
    expect(FIRST_AGENT_STEP).toBe('agent.tools')
    expect(agentTourSteps.map((item) => item.chapter)).toEqual([
      'agent',
      'agent',
      'agent',
      'agent',
      'review',
    ])
  })

  it('тексты страниц не длиннее 160 символов и без восклицаний', () => {
    for (const item of agentTourSteps) {
      for (const page of item.pages) {
        expect(page.text.length, `${item.key}: ${page.text}`).toBeLessThanOrEqual(160)
        expect(page.text).not.toContain('!')
      }
    }
  })

  it('экран — настройки; финал не привязан к маршруту', () => {
    for (const key of ['agent.tools', 'agent.tokens', 'agent.create-token', 'agent.copy-command']) {
      expect(step(key).route?.(ctx)).toEqual({ to: '/settings' })
    }
    expect(step('agent.review').route).toBeUndefined()
  })

  it('якоря: разделы настроек, кнопка токена и команда в окне', () => {
    expect(step('agent.tools').anchor).toBe(TOUR_ANCHORS.settingsTools)
    expect(step('agent.tools').pages[1]?.anchor).toBe(TOUR_ANCHORS.toolsAddKey)
    expect(step('agent.tokens').anchor).toBe(TOUR_ANCHORS.agentTokens)
    expect(step('agent.create-token').anchor).toBe(TOUR_ANCHORS.agentCreateToken)
    expect(step('agent.copy-command').anchor).toBe(TOUR_ANCHORS.agentCopyCommand)
    // Окно с командой могли закрыть: шаг пропускается, а не запирает тур.
    expect(step('agent.copy-command').optional).toBe(true)
  })

  it('действия завершаются сигналами создания токена и копирования команды', () => {
    const created: OnboardingSignal = { type: 'agent.token.created', id: 't1', name: 'Токен' }
    const copied: OnboardingSignal = { type: 'agent.command.copied' }
    expect(step('agent.create-token').until?.(created, ctx)).toBe(true)
    expect(step('agent.create-token').until?.(copied, ctx)).toBe(false)
    expect(step('agent.copy-command').until?.(copied, ctx)).toBe(true)
    expect(step('agent.copy-command').until?.(created, ctx)).toBe(false)
  })

  it('вид шага про доступ подстраивается под уже созданные токены', () => {
    expect(viewOf('agent.tokens').text).toContain('Токен — пропуск агента')
    expect(viewOf('agent.tokens', { tokenCount: 2 }).text).toContain('У вас уже есть токены')
  })

  it('финал предлагает пройти снова или закончить', () => {
    const view = viewOf('agent.review')
    expect(view.actions?.map((action) => action.label)).toEqual(['Пройти снова', 'Готово'])
  })
})
