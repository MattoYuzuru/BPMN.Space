import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { type OnboardingState, onboardingKeys } from '@/entities/onboarding'
import { sessionKeys } from '@/entities/session'
import type { Version } from '@/entities/version'
import { TooltipProvider } from '@/shared/ui'
import { stubApi } from '@/test/api-stub'
import { type WorkspaceApi, WorkspaceContext } from '@/widgets/workspace/model'
import { DownloadMenu } from './download-menu'

const USER = { id: 'u1', email: 'a@example.com' }
const state: OnboardingState = {
  enabled: true,
  tour: { status: 'completed', step: null, project_id: null, updated_at: '2026-10-04T10:00:00Z' },
  checklist: { hidden: false, items: [] },
  tour_text_suggestion: '',
}

const version = { id: 'v1', number: 1 } as unknown as Version

function mount() {
  const calls = stubApi({ 'POST /api/v1/me/onboarding/events': { status: 204 } })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(sessionKeys.all, { auth_enabled: true, user: USER })
  client.setQueryData(onboardingKeys.user(USER.id), state)
  const api = {
    project: { id: 'p1', title: 'Проект' },
    editorRef: { current: null },
    versions: { xmlUrl: (id: string) => `/api/v1/versions/${id}/xml` },
  } as unknown as WorkspaceApi
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <WorkspaceContext.Provider value={api}>
          <DownloadMenu version={version} />
        </WorkspaceContext.Provider>
      </TooltipProvider>
    </QueryClientProvider>,
  )
  return calls
}

const events = (calls: ReturnType<typeof stubApi>) =>
  calls.filter((call) => call.path === '/api/v1/me/onboarding/events')

describe('скачивание схемы и чек-лист', () => {
  beforeEach(() => {
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  })
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('первое скачивание сообщает diagram_exported, повторное — запроса не шлёт', async () => {
    const calls = mount()
    const user = userEvent.setup()
    const download = async () => {
      await user.click(screen.getByRole('button', { name: 'Скачать схему' }))
      await user.click(await screen.findByRole('menuitem', { name: /BPMN 2.0/ }))
    }
    await download()
    await waitFor(() => expect(events(calls)).toHaveLength(1))
    expect(events(calls)[0]?.body).toEqual({ item: 'diagram_exported' })

    await download()
    // отметка уже в кэше: даём время на лишний запрос, которого быть не должно
    await new Promise((resolve) => setTimeout(resolve, 30))
    expect(events(calls)).toHaveLength(1)
  })
})
