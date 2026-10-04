import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { type OnboardingState, onboardingKeys } from '@/entities/onboarding'
import { sessionKeys } from '@/entities/session'
import type { TourContext } from '@/features/onboarding/tour/context'
import { resetTourSession, useTourSession } from '@/features/onboarding/tour/session'
import { tourSteps } from '@/features/onboarding/tour/steps'
import { startTour, stopTour } from '@/features/onboarding/tour/store'
import { TooltipProvider } from '@/shared/ui'
import { stubApi } from '@/test/api-stub'
import TourRoot from './tour-root'

const captured = vi.hoisted(() => ({ context: undefined as TourContext | undefined }))
// Хост тура здесь не нужен: проверяем контекст, который ему отдаёт сборка.
vi.mock('@/features/onboarding/tour', async (original) => ({
  ...(await original<typeof import('@/features/onboarding/tour')>()),
  TourHost: (props: { context: TourContext }) => {
    captured.context = props.context
    return null
  },
}))
vi.mock('@/shared/ui', async (original) => ({
  ...(await original<typeof import('@/shared/ui')>()),
  toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }),
}))

const question = (id: string, status: string, n: number) => ({
  id,
  code: `Q-${n}`,
  status,
  severity: 'major',
  kind: 'missing_actor',
  text: 'Вопрос',
  element_ids: [],
  created_at: '2026-10-04T10:00:00Z',
  updated_at: '2026-10-04T10:00:00Z',
})

const project = (patch: Record<string, unknown> = {}) => ({
  id: 'p1',
  title: 'Мой первый процесс',
  sources: [{ id: 's1', kind: 'text', status: 'ready' }],
  questions: [question('q1', 'open', 1), question('q2', 'open', 2)],
  latest_version: { id: 'v1' },
  active_run: null,
  ...patch,
})

const state: OnboardingState = {
  enabled: true,
  tour: { status: 'active', step: 'run.wait', project_id: 'p1', updated_at: 'x' },
  checklist: { hidden: false, items: [] },
  tour_text_suggestion: 'Подсказка',
}

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(sessionKeys.all, { auth_enabled: true, user: { id: 'u1', email: 'a@b.c' } })
  client.setQueryData(onboardingKeys.user('u1'), state)
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <TourRoot state={state} />
      </TooltipProvider>
    </QueryClientProvider>,
  )
}

const step = (key: string) => tourSteps.find((item) => item.key === key)

beforeEach(() => {
  stopTour()
  resetTourSession()
  captured.context = undefined
})
afterEach(() => {
  vi.unstubAllGlobals()
})

describe('TourRoot: контекст шагов из данных учебного проекта', () => {
  it('после перезагрузки на шаге 6 итог прогона берётся из данных, если прогон уже закончился', async () => {
    stubApi({ 'GET /api/v1/projects/p1': { body: project() } })
    act(() => startTour('run.wait', { restored: true }))
    mount()
    await waitFor(() =>
      expect(captured.context?.result).toEqual({
        status: 'succeeded',
        openQuestions: 2,
        hasDiagram: true,
      }),
    )
    expect(step('run.wait')?.doneWhen?.(captured.context as TourContext)).toBe(true)
  })

  it('прогон ещё идёт — итога нет; «Повторить» ещё не стартовал — старые данные итогом не считаются', async () => {
    const running = stubApi({
      'GET /api/v1/projects/p1': { body: project({ active_run: { id: 'r1', status: 'running' } }) },
    })
    act(() => startTour('run.wait', { restored: true }))
    mount()
    await waitFor(() => expect(captured.context?.runActive).toBe(true))
    expect(captured.context?.result).toBeNull()
    expect(running.length).toBeGreaterThan(0)
  })

  it('«Повторить» без старта нового прогона: данные прежнего прогона итогом нового не становятся', async () => {
    stubApi({ 'GET /api/v1/projects/p1': { body: project() } })
    act(() => {
      startTour('run.wait', { restored: true })
      useTourSession.getState().setRetryPending(true)
    })
    mount()
    await waitFor(() => expect(captured.context?.loaded).toBe(true))
    expect(captured.context?.result).toBeNull()
  })

  it('перезагрузка на шаге 8 при двух вопросах: ответ в шаге 7 шаг не отменяет, цель — оставшийся открытый', async () => {
    stubApi({
      'GET /api/v1/projects/p1': {
        body: project({ questions: [question('q1', 'answered', 1), question('q2', 'open', 2)] }),
      },
    })
    act(() => startTour('question.ignore', { restored: true }))
    mount()
    await waitFor(() => expect(captured.context?.result?.openQuestions).toBe(2))
    const ctx = captured.context as TourContext
    expect(step('question.ignore')?.skipIf?.(ctx)).toBe(false)
    expect(ctx.openQuestionIds).toEqual(['q2'])
    expect(ctx.pickedId).toBeNull()
    const anchor = step('question.ignore')?.anchor
    expect(typeof anchor === 'function' && anchor(ctx)).toEqual({
      selector: '[data-question-id="q2"] [data-tour="question.ignore"]',
    })
  })

  it('учебный проект удалён (404) — контекст сообщает об этом', async () => {
    stubApi({ 'GET /api/v1/projects/p1': { status: 404, body: { detail: 'Проект не найден' } } })
    act(() => startTour('sources.text', { restored: true }))
    mount()
    await waitFor(() => expect(captured.context?.deleted).toBe(true))
  })

  it('очередь прогона: по данным проекта и по сигналу', async () => {
    stubApi({
      'GET /api/v1/projects/p1': { body: project({ active_run: { id: 'r1', status: 'queued' } }) },
    })
    act(() => startTour('run.wait', { restored: true }))
    mount()
    await waitFor(() => expect(captured.context?.queued).toBe(true))
  })

  it('вопрос шага 7 закрепляется при входе в шаг и не прыгает после ответа', async () => {
    stubApi({ 'GET /api/v1/projects/p1': { body: project() } })
    act(() => startTour('question.answer', { restored: true }))
    mount()
    await waitFor(() => expect(captured.context?.pickedId).toBe('q1'))
    // Оптимистичный ответ: q1 уже не открыт, а прожектор остаётся на нём.
    expect(useTourSession.getState().pickedId).toBe('q1')
  })
})
