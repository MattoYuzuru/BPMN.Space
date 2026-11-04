import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from '@tanstack/react-router'
import { render, screen } from '@testing-library/react'
import type { Question } from '@/entities/question'
import { TooltipProvider } from '@/shared/ui'
import { stubApi } from '@/test/api-stub'
import { useWorkspaceUi, type WorkspaceApi, WorkspaceContext } from '@/widgets/workspace/model'
import { QuestionsPanel } from './questions-panel'

const business: Question = {
  id: 'q1',
  project_id: 'p1',
  code: 'Q-1',
  kind: 'missing_actor',
  severity: 'major',
  status: 'open',
  text: 'Кто согласует бюджет?',
  assumption: 'Руководитель отдела',
  element_ids: [],
  category: 'business',
  blocking: false,
  created_at: '2026-11-04T10:00:00Z',
  updated_at: '2026-11-04T10:00:00Z',
}

const technical: Question = {
  ...business,
  id: 'tq1',
  code: 'TQ-1',
  kind: 'quota_exhausted',
  category: 'technical',
  blocking: true,
  text: 'У распознавания речи закончилась квота: не расшифровано 46 из 80 минут.',
  actions: [{ kind: 'open_settings', label: 'Открыть настройки' }],
}

const project = {
  id: 'p1',
  title: 'Проект',
  status: 'analyzing',
  sources: [],
  questions: [business, technical],
  latest_version: null,
  summary: { resolved: 0, open: 1, new: 0, ignored: 0, answered: 0 },
  counts: { versions: 0 },
}

function mount() {
  stubApi({})
  const api = {
    project,
    canEdit: true,
    selectedQuestionId: undefined,
    selectQuestion: vi.fn(),
    focusElements: vi.fn(),
  } as unknown as WorkspaceApi
  const router = createRouter({
    routeTree: createRootRoute({
      component: () => (
        <WorkspaceContext.Provider value={api}>
          <QuestionsPanel onCollapse={vi.fn()} />
        </WorkspaceContext.Provider>
      ),
    }),
    history: createMemoryHistory({ initialEntries: ['/'] }),
  })
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <TooltipProvider>
        <RouterProvider router={router} />
      </TooltipProvider>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  useWorkspaceUi.getState().reset()
  vi.unstubAllGlobals()
})

describe('вкладка технических вопросов', () => {
  it('выносит технический вопрос из бизнес-вкладок в отдельную', async () => {
    mount()
    const open = await screen.findByRole('tab', { name: /Открытые/ })
    expect(open).toHaveTextContent('1')
    const tab = screen.getByRole('tab', { name: /Технические/ })
    expect(tab).toHaveTextContent('1')
    expect(screen.queryByText(/закончилась квота/)).toBeNull()
  })

  it('показывает карточку с действиями технического вопроса', async () => {
    const { container } = mount()
    const { default: userEvent } = await import('@testing-library/user-event')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('tab', { name: /Технические/ }))
    expect(screen.getByText(/закончилась квота/)).toBeInTheDocument()
    expect(screen.getByText('Блокирует прогон')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Открыть настройки' })).toBeInTheDocument()
    expect(container).toBeTruthy()
  })
})
