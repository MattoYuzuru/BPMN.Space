import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import {
  type OnboardingState,
  onboardingKeys,
  type TourState,
  useOnboardingUi,
} from '@/entities/onboarding'
import { sessionKeys } from '@/entities/session'
import { useTourStore } from '@/features/onboarding/tour/store'
import { stubApi } from '@/test/api-stub'
import ChecklistSheet from './checklist-sheet'

vi.mock('@tanstack/react-router', async (original) => ({
  ...(await original<typeof import('@tanstack/react-router')>()),
  useNavigate: () => vi.fn(),
}))

const USER = { id: 'u1', email: 'a@example.com' }

function tour(status: TourState['status']): TourState {
  return { status, step: null, project_id: null, updated_at: '2026-10-04T10:00:00Z' }
}

function state(
  status: TourState['status'] = 'completed',
  hidden = false,
  doneCount = 2,
): OnboardingState {
  const keys = ['project_created', 'text_source_added', 'document_uploaded'] as const
  return {
    enabled: true,
    tour: tour(status),
    checklist: {
      hidden,
      items: keys.slice(0, doneCount).map((key) => ({
        key,
        completed_at: '2026-10-04T10:00:00Z',
        source: 'server' as const,
      })),
    },
    tour_text_suggestion: '',
  }
}

function mount(initial: OnboardingState) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(sessionKeys.all, { auth_enabled: true, user: USER })
  client.setQueryData(onboardingKeys.user(USER.id), initial)
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  act(() => useOnboardingUi.getState().openChecklist())
  render(<ChecklistSheet />, { wrapper })
  return client
}

afterEach(() => {
  vi.unstubAllGlobals()
  act(() => {
    useTourStore.getState().stop()
    useOnboardingUi.getState().closeChecklist()
  })
})

describe('панель «Начало работы»: кнопки внизу', () => {
  it('заголовок, прогресс и 12 пунктов', async () => {
    mount(state())
    expect(await screen.findByRole('dialog', { name: 'Начало работы' })).toBeInTheDocument()
    expect(screen.getByText('2 из 12')).toBeInTheDocument()
    expect(screen.getAllByRole('listitem')).toHaveLength(12)
  })

  it('«Пройти обучение заново»: перезапуск на сервере, закрытие панели, запуск тура', async () => {
    const calls = stubApi({
      'POST /api/v1/me/onboarding/tour/restart': {
        body: { ...state('active'), tour: { ...tour('active'), step: 'project.create' } },
      },
    })
    mount(state())
    await userEvent.click(await screen.findByRole('button', { name: 'Пройти обучение заново' }))
    await waitFor(() => expect(useTourStore.getState().status).toBe('active'))
    expect(useTourStore.getState().stepKey).toBe('project.create')
    expect(calls.some((c) => c.path === '/api/v1/me/onboarding/tour/restart')).toBe(true)
    expect(useOnboardingUi.getState().checklistOpen).toBe(false)
  })

  it('при ошибке перезапуска тур не стартует и панель остаётся', async () => {
    stubApi({ 'POST /api/v1/me/onboarding/tour/restart': { status: 500, body: { detail: 'x' } } })
    mount(state())
    await userEvent.click(await screen.findByRole('button', { name: 'Пройти обучение заново' }))
    await waitFor(() => expect(screen.getByRole('button', { name: /заново/ })).toBeEnabled())
    expect(useTourStore.getState().status).toBe('idle')
    expect(useOnboardingUi.getState().checklistOpen).toBe(true)
  })

  it('тур идёт: «Продолжить обучение», пункты недоступны, запроса перезапуска нет', async () => {
    const calls = stubApi({})
    mount(state('active'))
    expect(screen.queryByRole('button', { name: 'Пройти обучение заново' })).not.toBeInTheDocument()
    expect(screen.getByText('Доступно после обучения')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Ответить на вопрос/ })).toBeDisabled()

    act(() => useTourStore.getState().start('source.add'))
    act(() => useTourStore.getState().setPaused(true))
    await userEvent.click(screen.getByRole('button', { name: 'Продолжить обучение' }))
    expect(useOnboardingUi.getState().checklistOpen).toBe(false)
    expect(useTourStore.getState().paused).toBe(false)
    expect(calls.filter((c) => c.path.includes('restart'))).toHaveLength(0)
  })

  it('«Продолжить обучение», когда локально тур не запущен: стартует с шага сервера', async () => {
    const active = state('active')
    if (active.tour) active.tour.step = 'run.start'
    stubApi({})
    mount(active)
    await userEvent.click(await screen.findByRole('button', { name: 'Продолжить обучение' }))
    expect(useTourStore.getState().status).toBe('active')
    expect(useTourStore.getState().stepKey).toBe('run.start')
  })

  it('«Скрыть чек-лист» шлёт hidden: true и сразу меняет подпись на «Показывать прогресс»', async () => {
    const calls = stubApi({
      'PATCH /api/v1/me/onboarding/checklist': { body: state('completed', true) },
    })
    mount(state())
    await userEvent.click(await screen.findByRole('button', { name: 'Скрыть чек-лист' }))
    expect(await screen.findByRole('button', { name: 'Показывать прогресс' })).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ hidden: true })
  })

  it('скрытый чек-лист: «Показывать прогресс» шлёт hidden: false', async () => {
    const calls = stubApi({
      'PATCH /api/v1/me/onboarding/checklist': { body: state('completed', false) },
    })
    mount(state('completed', true))
    await userEvent.click(await screen.findByRole('button', { name: 'Показывать прогресс' }))
    await waitFor(() =>
      expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ hidden: false }),
    )
  })

  it('все пункты выполнены: кнопки «Скрыть» нет', async () => {
    const full = state()
    full.checklist = {
      hidden: false,
      items: [
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
      ].map((key) => ({
        key: key as never,
        completed_at: '2026-10-04T10:00:00Z',
        source: 'server' as const,
      })),
    }
    mount(full)
    await screen.findByRole('dialog')
    expect(screen.queryByRole('button', { name: 'Скрыть чек-лист' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Пройти обучение заново' })).toBeInTheDocument()
  })
})
