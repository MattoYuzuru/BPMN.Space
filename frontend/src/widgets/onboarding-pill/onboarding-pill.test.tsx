import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import {
  type ChecklistItemKey,
  type OnboardingState,
  onboardingKeys,
  useOnboardingUi,
} from '@/entities/onboarding'
import { sessionKeys } from '@/entities/session'
import { useTourStore } from '@/features/onboarding/tour/store'
import { OnboardingPill, PILL_DELAY_AFTER_TOUR_MS } from './onboarding-pill'

let matched: string | null = '/_app/projects/'
vi.mock('@tanstack/react-router', async (original) => ({
  ...(await original<typeof import('@tanstack/react-router')>()),
  useMatch: ({ from }: { from: string }) => (from === matched ? { routeId: from } : undefined),
}))

const USER = { id: 'u1', email: 'a@example.com' }
const KEYS: ChecklistItemKey[] = [
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
]

function state(
  count: number,
  patch: { hidden?: boolean; tour?: 'pending' | 'active' | 'completed'; enabled?: boolean } = {},
): OnboardingState {
  if (patch.enabled === false) return { enabled: false }
  return {
    enabled: true,
    tour: {
      status: patch.tour ?? 'completed',
      step: null,
      project_id: null,
      updated_at: '2026-10-04T10:00:00Z',
    },
    checklist: {
      hidden: patch.hidden ?? false,
      items: KEYS.slice(0, count).map((key) => ({
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
  const view = render(<OnboardingPill />, { wrapper })
  const set = async (next: OnboardingState) =>
    act(async () => {
      client.setQueryData(onboardingKeys.user(USER.id), next)
      await new Promise((resolve) => setTimeout(resolve, 5))
    })
  return { ...view, set }
}

const pill = () => screen.queryByRole('button', { name: /Начало работы/ })

beforeEach(() => {
  matched = '/_app/projects/'
})

afterEach(() => {
  vi.useRealTimers()
  act(() => {
    useTourStore.getState().stop()
    useOnboardingUi.getState().closeChecklist()
  })
  document.body.replaceChildren()
})

describe('плашка прогресса', () => {
  it('на экране проектов показывает «Начало работы» и счётчик, клик открывает панель', async () => {
    mount(state(5))
    const button = await screen.findByRole('button', { name: 'Начало работы, выполнено 5 из 12' })
    expect(button).toHaveTextContent('5/12')
    await userEvent.click(button)
    expect(useOnboardingUi.getState().checklistOpen).toBe(true)
  })

  it('на главной (тоже экран проектов) видна', async () => {
    matched = '/_app/'
    mount(state(0))
    expect(await screen.findByRole('button', { name: /Начало работы/ })).toBeInTheDocument()
  })

  it('в рабочем пространстве её нет', () => {
    matched = null
    mount(state(5))
    expect(pill()).not.toBeInTheDocument()
  })

  it('нет, если чек-лист скрыт, завершён или онбординг выключен', () => {
    mount(state(5, { hidden: true }))
    expect(pill()).not.toBeInTheDocument()
    document.body.replaceChildren()
    mount(state(12))
    expect(pill()).not.toBeInTheDocument()
    document.body.replaceChildren()
    mount(state(0, { enabled: false }))
    expect(pill()).not.toBeInTheDocument()
  })

  it('нет, пока идёт тур; появляется через секунду после его конца', async () => {
    const { set } = mount(state(3, { tour: 'active' }))
    expect(pill()).not.toBeInTheDocument()
    vi.useFakeTimers({ shouldAdvanceTime: true })
    await set(state(3, { tour: 'completed' }))
    expect(pill()).not.toBeInTheDocument()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(PILL_DELAY_AFTER_TOUR_MS + 50)
    })
    expect(await screen.findByRole('button', { name: /Начало работы/ })).toBeInTheDocument()
  })

  it('прячется, пока открыта панель или на экране окно', async () => {
    mount(state(5))
    await screen.findByRole('button', { name: /Начало работы/ })
    act(() => useOnboardingUi.getState().openChecklist())
    expect(pill()).not.toBeInTheDocument()
    act(() => useOnboardingUi.getState().closeChecklist())
    expect(await screen.findByRole('button', { name: /Начало работы/ })).toBeInTheDocument()

    const dialog = document.createElement('div')
    dialog.setAttribute('role', 'dialog')
    await act(async () => {
      document.body.append(dialog)
      await new Promise((resolve) => setTimeout(resolve, 5))
    })
    expect(pill()).not.toBeInTheDocument()
  })
})
