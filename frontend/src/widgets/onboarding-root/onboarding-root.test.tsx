import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { type OnboardingState, onboardingKeys } from '@/entities/onboarding'
import { sessionKeys } from '@/entities/session'
import { stopTour, useTourStore } from '@/features/onboarding/tour'
import { Dialog, DialogContent, TooltipProvider } from '@/shared/ui'
import { stubApi } from '@/test/api-stub'
import { OnboardingRoot } from './onboarding-root'

const toast = vi.hoisted(() => vi.fn())
vi.mock('@/shared/ui', async (original) => ({
  ...(await original<typeof import('@/shared/ui')>()),
  toast: Object.assign(toast, { error: vi.fn(), success: vi.fn() }),
}))
// Сборка тура грузится лениво и сама тяжёлая: здесь проверяем только приветствие и запуск.
vi.mock('./tour-root', () => ({ default: () => <div data-testid="tour-root" /> }))

const state = (patch: Partial<OnboardingState> = {}): OnboardingState => ({
  enabled: true,
  tour: { status: 'pending', step: null, project_id: null, updated_at: '2026-10-04T10:00:00Z' },
  checklist: { hidden: false, items: [] },
  tour_text_suggestion: 'Подсказка',
  ...patch,
})

function mount(initial: OnboardingState, extra?: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  client.setQueryData(sessionKeys.all, {
    auth_enabled: true,
    user: { id: 'u1', email: 'a@example.com' },
  })
  client.setQueryData(onboardingKeys.user('u1'), initial)
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        {extra}
        <OnboardingRoot />
      </TooltipProvider>
    </QueryClientProvider>,
  )
  return { client, user }
}

const welcome = () => screen.queryByRole('dialog', { name: 'Добро пожаловать в Архитектор' })
const advance = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms))

// Ленивый чанк приветствия загружаем заранее: тесты управляют только временем.
beforeAll(() => import('./onboarding-gate'))

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  stopTour()
  toast.mockReset()
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('OnboardingRoot: приветствие', () => {
  it('появляется с паузой ~400 мс, когда тур ещё не предлагали', async () => {
    mount(state())
    expect(welcome()).toBeNull()
    await advance(200)
    expect(welcome()).toBeNull()
    await advance(400)
    expect(welcome()).not.toBeNull()
  })

  it.each([
    ['онбординг выключен', { enabled: false, tour: null }],
    [
      'тур уже отклонён',
      { tour: { status: 'dismissed' as const, step: null, project_id: null, updated_at: 'x' } },
    ],
    [
      'тур пройден',
      { tour: { status: 'completed' as const, step: null, project_id: null, updated_at: 'x' } },
    ],
  ])('не показывается: %s', async (_name, patch) => {
    mount(state(patch as Partial<OnboardingState>))
    await advance(1500)
    expect(welcome()).toBeNull()
  })

  it('ждёт, пока закроется другое окно', async () => {
    const other = (
      <Dialog open>
        <DialogContent title="Другое окно" aria-describedby={undefined}>
          Занято
        </DialogContent>
      </Dialog>
    )
    mount(state(), other)
    await advance(1500)
    expect(welcome()).toBeNull()
  })

  it('«Я уже знаком»: PATCH dismissed и уведомление', async () => {
    const calls = stubApi({
      'PATCH /api/v1/me/onboarding/tour': (call) => ({
        body: state({
          tour: {
            status: (call.body as { status: 'dismissed' }).status,
            step: null,
            project_id: null,
            updated_at: 'x',
          },
        }),
      }),
    })
    const { user } = mount(state())
    await advance(600)
    await user.click(screen.getByRole('button', { name: 'Я уже знаком' }))
    await advance(50)
    expect(calls.find((call) => call.method === 'PATCH')?.body).toEqual({ status: 'dismissed' })
    expect(toast).toHaveBeenCalledWith('Обучение всегда можно пройти в меню аккаунта')
    expect(welcome()).toBeNull()
    expect(useTourStore.getState().status).toBe('idle')
  })

  it('Esc равен «Я уже знаком»', async () => {
    const calls = stubApi({
      'PATCH /api/v1/me/onboarding/tour': {
        body: state({
          tour: { status: 'dismissed', step: null, project_id: null, updated_at: 'x' },
        }),
      },
    })
    const { user } = mount(state())
    await advance(600)
    await user.keyboard('{Escape}')
    await advance(50)
    expect(calls.find((call) => call.method === 'PATCH')?.body).toEqual({ status: 'dismissed' })
  })

  it('«Пройти обучение»: PATCH active с шагом project.create, затем старт тура', async () => {
    const calls = stubApi({
      'PATCH /api/v1/me/onboarding/tour': {
        body: state({
          tour: {
            status: 'active',
            step: 'project.create',
            project_id: null,
            updated_at: 'x',
          },
        }),
      },
    })
    const { user } = mount(state())
    await advance(600)
    await user.click(screen.getByRole('button', { name: 'Пройти обучение' }))
    await advance(50)
    expect(calls.find((call) => call.method === 'PATCH')?.body).toEqual({
      status: 'active',
      step: 'project.create',
    })
    expect(useTourStore.getState()).toMatchObject({ status: 'active', stepKey: 'project.create' })
    expect(welcome()).toBeNull()
    expect(await screen.findByTestId('tour-root')).toBeInTheDocument()
  })
})

describe('OnboardingRoot: сборка тура', () => {
  it('грузится сразу, если сервер говорит, что тур идёт', async () => {
    mount(
      state({
        tour: { status: 'active', step: 'sources.text', project_id: 'p1', updated_at: 'x' },
      }),
    )
    expect(await screen.findByTestId('tour-root')).toBeInTheDocument()
    expect(welcome()).toBeNull()
  })

  it('без тура сборка не грузится вовсе', async () => {
    mount(state({ tour: { status: 'dismissed', step: null, project_id: null, updated_at: 'x' } }))
    await advance(800)
    expect(screen.queryByTestId('tour-root')).toBeNull()
  })
})
