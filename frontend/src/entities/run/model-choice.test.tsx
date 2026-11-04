import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { useModelChoiceStore } from '@/entities/llm-credential'
import { type ProjectDetail, projectKeys } from '@/entities/project'
import { sessionKeys } from '@/entities/session'
import { stubApi } from '@/test/api-stub'
import { useStartRun } from './api'

vi.mock('@/shared/ui', async (original) => ({
  ...(await original<typeof import('@/shared/ui')>()),
  toast: Object.assign(vi.fn(), { error: vi.fn() }),
}))

afterEach(() => vi.unstubAllGlobals())

function setup() {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
  client.setQueryData(projectKeys.detail('p-1'), { id: 'p-1', status: 'empty' } as ProjectDetail)
  client.setQueryData(sessionKeys.all, { auth_enabled: true, user: { id: 'u1', email: 'a@b.ru' } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  return renderHook(() => useStartRun('p-1'), { wrapper })
}

describe('запуск прогона с выбранной моделью', () => {
  it('отправляет ключ и модель, выбранные пользователем', async () => {
    useModelChoiceStore.setState({
      choices: { u1: { credentialId: 'c1', model: 'claude-sonnet-5-5' } },
    })
    const calls = stubApi({
      'POST /api/v1/projects/p-1/runs': {
        status: 202,
        body: { id: 'r-1', project_id: 'p-1', mode: 'build', status: 'queued' },
      },
    })
    const hook = setup()
    await act(async () => {
      await hook.result.current.mutateAsync('build')
    })
    expect(calls.at(-1)?.body).toMatchObject({
      mode: 'build',
      credential_id: 'c1',
      model: 'claude-sonnet-5-5',
    })
  })

  it('без выбора не отправляет ничего лишнего: решает сервер', async () => {
    useModelChoiceStore.setState({ choices: { u1: null } })
    const calls = stubApi({
      'POST /api/v1/projects/p-1/runs': {
        status: 202,
        body: { id: 'r-2', project_id: 'p-1', mode: 'analyze', status: 'queued' },
      },
    })
    const hook = setup()
    await act(async () => {
      await hook.result.current.mutateAsync('analyze')
    })
    const body = calls.at(-1)?.body as Record<string, unknown>
    expect(body).not.toHaveProperty('credential_id')
    expect(body).not.toHaveProperty('model')
  })
})
