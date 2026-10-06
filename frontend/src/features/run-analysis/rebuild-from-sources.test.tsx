import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { screen, waitFor } from '@testing-library/react'
import { useRunStore } from '@/entities/run'
import { TooltipProvider } from '@/shared/ui'
import { stubApi } from '@/test/api-stub'
import { renderUi } from '@/test/render'
import { RebuildFromSources } from './rebuild-from-sources'

vi.mock('@/shared/ui', async (original) => ({
  ...(await original<typeof import('@/shared/ui')>()),
  toast: Object.assign(vi.fn(), { error: vi.fn() }),
}))

afterEach(() => vi.unstubAllGlobals())

function panel(baseVersionId: string, client: QueryClient) {
  return (
    <QueryClientProvider client={client}>
      <RebuildFromSources projectId="p1" baseVersionId={baseVersionId} disabled={false} />
    </QueryClientProvider>
  )
}

it('перестроение требует подтверждения и отправляет голову, показанную при открытии', async () => {
  useRunStore.setState({ views: {}, expanded: {}, presented: {} })
  const calls = stubApi({
    'POST /api/v1/projects/p1/runs': {
      status: 202,
      body: { id: 'r1', project_id: 'p1', mode: 'build', status: 'queued' },
    },
  })
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
  const ui = renderUi(panel('version-1', client))
  await ui.user.click(screen.getByRole('button', { name: 'Другие способы построения' }))
  await ui.user.click(screen.getByRole('menuitem', { name: 'Перестроить из источников' }))
  expect(screen.getByRole('alertdialog')).toHaveTextContent(
    'Текущая схема останется в истории версий',
  )
  expect(calls.filter((call) => call.method === 'POST')).toHaveLength(0)
  // Коллега изменил голову, пока аналитик читает предупреждение: подтверждение старой головы
  // не становится разрешением заменить новую. Backend проверяет этот id ещё раз.
  ui.rerender(<TooltipProvider>{panel('version-2', client)}</TooltipProvider>)
  await ui.user.click(screen.getByRole('button', { name: 'Перестроить' }))
  await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
  expect(calls.find((call) => call.method === 'POST')?.body).toEqual({
    mode: 'build',
    replace_manual: true,
    base_version_id: 'version-1',
  })
  expect(useRunStore.getState().views.p1?.runId).toBe('r1')
})

it('отмена предупреждения не запускает прогон', async () => {
  const calls = stubApi({})
  const { user } = renderUi(panel('version-1', new QueryClient()))
  await user.click(screen.getByRole('button', { name: 'Другие способы построения' }))
  await user.click(screen.getByRole('menuitem', { name: 'Перестроить из источников' }))
  await user.click(screen.getByRole('button', { name: 'Отмена' }))
  expect(calls.filter((call) => call.method === 'POST')).toHaveLength(0)
})

it('409 оставляет предупреждение доступным и не подменяет подтверждённую голову', async () => {
  stubApi({
    'POST /api/v1/projects/p1/runs': {
      status: 409,
      body: { detail: 'Схема уже изменена другим участником' },
    },
  })
  const { user } = renderUi(panel('version-1', new QueryClient()))
  await user.click(screen.getByRole('button', { name: 'Другие способы построения' }))
  await user.click(screen.getByRole('menuitem', { name: 'Перестроить из источников' }))
  await user.click(screen.getByRole('button', { name: 'Перестроить' }))
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Перестроить' })).not.toBeDisabled(),
  )
  expect(screen.getByRole('alertdialog')).toBeVisible()
})
