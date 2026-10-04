import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from '@tanstack/react-router'
import { render, screen } from '@testing-library/react'
import { TooltipProvider } from '@/shared/ui'
import { stubApi } from '@/test/api-stub'
import { type WorkspaceApi, WorkspaceContext } from '@/widgets/workspace/model'
import { ProjectHeader } from './project-header'

// Нас интересует только условие показа кнопки; шапка приложения и диалог — отдельно.
vi.mock('@/features/share-project/share-project-button', () => ({
  ShareProjectButton: () => <button type="button">Поделиться</button>,
}))
vi.mock('@/widgets/app-header/app-header', () => ({
  AppHeader: ({ actions }: { actions: React.ReactNode }) => <header>{actions}</header>,
}))

const project = {
  id: 'p1',
  title: 'Проект',
  status: 'ready',
  sources: [],
  questions: [],
  latest_version: null,
  summary: {},
  counts: { versions: 0 },
}

function mount(capabilities: Pick<WorkspaceApi, 'canEdit' | 'canManage' | 'canShare'>) {
  stubApi({})
  const api = {
    project,
    versions: { list: () => ({ queryKey: ['v'], queryFn: async () => [] }) },
    ...capabilities,
  } as unknown as WorkspaceApi
  const router = createRouter({
    routeTree: createRootRoute({
      component: () => (
        <WorkspaceContext.Provider value={api}>
          <ProjectHeader />
        </WorkspaceContext.Provider>
      ),
    }),
    history: createMemoryHistory({ initialEntries: ['/'] }),
  })
  render(
    <QueryClientProvider client={new QueryClient()}>
      <TooltipProvider>
        <RouterProvider router={router} />
      </TooltipProvider>
    </QueryClientProvider>,
  )
}

describe('шапка проекта: «Поделиться»', () => {
  it('есть, когда делиться можно', async () => {
    mount({ canEdit: true, canManage: true, canShare: true })
    expect(await screen.findByRole('button', { name: 'Поделиться' })).toBeInTheDocument()
  })

  it('нет у владельца без аккаунтов: canManage есть, canShare нет', async () => {
    mount({ canEdit: true, canManage: true, canShare: false })
    await screen.findByRole('button', { name: 'Анализ' })
    expect(screen.queryByRole('button', { name: 'Поделиться' })).not.toBeInTheDocument()
  })
})
