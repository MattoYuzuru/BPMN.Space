import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { type OnboardingState, onboardingKeys } from '@/entities/onboarding'
import { sessionKeys } from '@/entities/session'
import { TooltipProvider } from '@/shared/ui'
import { stubApi } from '@/test/api-stub'
import { type WorkspaceApi, WorkspaceContext } from '@/widgets/workspace/model'
import { DiagramToolbar } from './diagram-toolbar'

const USER = { id: 'u1', email: 'a@example.com' }
const state: OnboardingState = {
  enabled: true,
  tour: { status: 'completed', step: null, project_id: null, updated_at: '2026-10-04T10:00:00Z' },
  checklist: { hidden: false, items: [] },
  tour_text_suggestion: '',
}

function mount(toggle: (active?: boolean) => boolean) {
  const calls = stubApi({ 'POST /api/v1/me/onboarding/events': { status: 204 } })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(sessionKeys.all, { auth_enabled: true, user: USER })
  client.setQueryData(onboardingKeys.user(USER.id), state)
  const api = {
    editorRef: { current: { toggleSimulation: toggle } },
    viewVersion: () => {},
    versions: {},
  } as unknown as WorkspaceApi
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <WorkspaceContext.Provider value={api}>
          <DiagramToolbar
            latestNumber={1}
            isLatest
            ready
            saving={false}
            saved={false}
            markers={{ assumptions: false, added: false }}
            onMarkersChange={() => {}}
            propertiesOpen={false}
            onPropertiesToggle={() => {}}
          />
        </WorkspaceContext.Provider>
      </TooltipProvider>
    </QueryClientProvider>,
  )
  return calls
}

const events = (calls: ReturnType<typeof stubApi>) =>
  calls.filter((call) => call.path === '/api/v1/me/onboarding/events')

afterEach(() => vi.unstubAllGlobals())

describe('таймлайн процесса и чек-лист', () => {
  it('включение сообщает simulation_run один раз, выключение — ничего не шлёт', async () => {
    let active = false
    const calls = mount(() => {
      active = !active
      return active
    })
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Таймлайн процесса' }))
    await waitFor(() => expect(events(calls)).toHaveLength(1))
    expect(events(calls)[0]?.body).toEqual({ item: 'simulation_run' })

    await user.click(screen.getByRole('button', { name: 'Остановить таймлайн' }))
    await user.click(screen.getByRole('button', { name: 'Таймлайн процесса' }))
    await new Promise((resolve) => setTimeout(resolve, 30))
    expect(events(calls)).toHaveLength(1)
  })
})
