import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { type VersionPagesData, type VersionSummary, versionKeys } from '@/entities/version'
import { useWorkspaceUi, type WorkspaceApi, WorkspaceContext } from '@/widgets/workspace/model'
import { VersionsSheet } from './versions-sheet'

const base = {
  project_id: 'p-1',
  run_id: null,
  actor_email: 'a@example.com',
  diff: { added: 0, removed: 0, changed: 0 },
  lint_count: 0,
  assumption_count: 0,
  label: null,
  checkpoint: false,
} as const

const items: VersionSummary[] = [
  {
    ...base,
    id: 'v-3',
    number: 3,
    origin: 'manual',
    created_at: '2026-10-07T11:05:00Z',
    session_started_at: '2026-10-07T11:05:00Z',
    updated_at: '2026-10-07T11:32:00Z',
    saved_count: 14,
  },
  {
    ...base,
    id: 'v-2',
    number: 2,
    origin: 'manual',
    checkpoint: true,
    label: 'Согласовано с заказчиком',
    created_at: '2026-10-07T10:00:00Z',
    session_started_at: '2026-10-07T10:00:00Z',
    updated_at: '2026-10-07T10:10:00Z',
    saved_count: 3,
  },
  {
    ...base,
    id: 'v-1',
    number: 1,
    origin: 'generated',
    created_at: '2026-10-07T09:00:00Z',
    session_started_at: '2026-10-07T09:00:00Z',
    updated_at: '2026-10-07T09:00:00Z',
    saved_count: 1,
  },
]

function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { staleTime: Number.POSITIVE_INFINITY } },
  })
  const data: VersionPagesData = {
    pages: [{ items, next_before: null }],
    pageParams: [undefined],
  }
  client.setQueryData(versionKeys.pages('p-1'), data)
  useWorkspaceUi.setState({ sheet: 'versions' })
  const workspace = {
    project: { id: 'p-1', latest_version: items[0] },
    viewVersion: () => {},
    versions: {
      pages: () => ({
        queryKey: versionKeys.pages('p-1'),
        initialPageParam: undefined,
        queryFn: async () => ({ items: [], next_before: null }),
        getNextPageParam: () => undefined,
      }),
      detail: (id: string) => ({ queryKey: ['d', id], queryFn: async () => null }),
    },
  } as unknown as WorkspaceApi
  return render(
    <QueryClientProvider client={client}>
      <WorkspaceContext.Provider value={workspace}>
        <VersionsSheet />
      </WorkspaceContext.Provider>
    </QueryClientProvider>,
  )
}

afterEach(() => useWorkspaceUi.setState({ sheet: null }))

describe('история версий', () => {
  it('различает контрольную точку, сессию правок и сборку', () => {
    mount()
    const rows = within(screen.getByRole('list', { name: 'Версии схемы' })).getAllByRole('listitem')
    expect(rows).toHaveLength(3)
    expect(rows[0]).toHaveTextContent(/Правки, .*14 автосохранений/)
    expect(rows[1]).toHaveTextContent('Согласовано с заказчиком')
    expect(rows[2]).toHaveTextContent('Сборка по источникам')
  })

  it('кнопка сравнения раскрывает панель и сообщает об этом', async () => {
    mount()
    const [toggle] = screen.getAllByRole('button', { name: 'Что изменилось' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await userEvent.click(toggle as HTMLElement)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
  })

  it('«Открыть» называет версию', () => {
    mount()
    expect(screen.getByRole('button', { name: 'Открыть версию 2' })).toBeInTheDocument()
  })
})
