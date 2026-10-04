import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { type OnboardingState, onboardingKeys, useOnboardingUi } from '@/entities/onboarding'
import { sessionKeys } from '@/entities/session'
import { TooltipProvider } from '@/shared/ui'
import { AccountMenu } from './account-menu'

vi.mock('@tanstack/react-router', async (original) => ({
  ...(await original<typeof import('@tanstack/react-router')>()),
  useNavigate: () => vi.fn(),
}))

const USER = { id: 'u1', email: 'anna@example.com' }

function onboarding(done: number, enabled = true): OnboardingState {
  if (!enabled) return { enabled: false }
  const keys = ['project_created', 'text_source_added', 'document_uploaded'] as const
  return {
    enabled: true,
    tour: { status: 'completed', step: null, project_id: null, updated_at: '2026-10-04T10:00:00Z' },
    checklist: {
      hidden: true, // пункт меню есть и при скрытом чек-листе
      items: keys.slice(0, done).map((key) => ({
        key,
        completed_at: '2026-10-04T10:00:00Z',
        source: 'server' as const,
      })),
    },
    tour_text_suggestion: '',
  }
}

function mount(state: OnboardingState | undefined, props: { withChecklist?: boolean } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(sessionKeys.all, { auth_enabled: true, user: USER })
  if (state) client.setQueryData(onboardingKeys.user(USER.id), state)
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <AccountMenu {...props} />
      </TooltipProvider>
    </QueryClientProvider>,
  )
}

async function openMenu() {
  await userEvent.click(screen.getByRole('button', { name: 'Аккаунт' }))
}

afterEach(() => act(() => useOnboardingUi.getState().closeChecklist()))

describe('меню аккаунта: «Начало работы»', () => {
  it('между почтой и «Выйти», со счётчиком; клик открывает панель', async () => {
    mount(onboarding(2))
    await openMenu()
    const items = (await screen.findAllByRole('menuitem')).map((item) => item.textContent)
    expect(items[0]).toContain('Начало работы')
    expect(items[0]).toContain('2/12')
    expect(items[1]).toBe('Выйти')
    await userEvent.click(screen.getByRole('menuitem', { name: /Начало работы/ }))
    expect(useOnboardingUi.getState().checklistOpen).toBe(true)
  })

  it('пункт остаётся и при скрытом чек-листе (в onboarding(…) hidden: true)', async () => {
    mount(onboarding(0))
    await openMenu()
    expect(await screen.findByRole('menuitem', { name: /Начало работы/ })).toBeInTheDocument()
  })

  it('все двенадцать — кольцо зелёное с галочкой', async () => {
    const full = onboarding(3)
    if (full.enabled && full.checklist) {
      full.checklist.items = Array.from({ length: 12 }, (_, index) => ({
        key: `k${index}` as never,
        completed_at: '2026-10-04T10:00:00Z',
        source: 'server' as const,
      }))
    }
    mount(full)
    await openMenu()
    const item = await screen.findByRole('menuitem', { name: /Начало работы/ })
    expect(item).toHaveTextContent('12/12')
    expect(item.querySelector('[data-complete]')).not.toBeNull()
  })

  it('онбординг выключен или не загружен — пункта нет', async () => {
    mount(onboarding(0, false))
    await openMenu()
    await screen.findByRole('menuitem', { name: 'Выйти' })
    expect(screen.queryByRole('menuitem', { name: /Начало работы/ })).not.toBeInTheDocument()
  })

  it('на публичных страницах (withChecklist=false) пункта нет', async () => {
    mount(onboarding(1), { withChecklist: false })
    await openMenu()
    await screen.findByRole('menuitem', { name: 'Выйти' })
    expect(screen.queryByRole('menuitem', { name: /Начало работы/ })).not.toBeInTheDocument()
  })
})
