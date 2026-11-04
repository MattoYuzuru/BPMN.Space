import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { llmCredentialKeys, useModelChoiceStore } from '@/entities/llm-credential'
import { type ProjectDetail, projectKeys } from '@/entities/project'
import { sessionKeys } from '@/entities/session'
import { stubApi } from '@/test/api-stub'
import { useStartRun } from './api'

vi.mock('@/shared/ui', async (original) => ({
  ...(await original<typeof import('@/shared/ui')>()),
  toast: Object.assign(vi.fn(), { error: vi.fn() }),
}))

afterEach(() => vi.unstubAllGlobals())

function setup({ models }: { models?: unknown[] } = {}) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
  if (models) client.setQueryData(llmCredentialKeys.models('c1'), models)
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

  it('отправляет показанный уровень, только если возможности модели известны', async () => {
    useModelChoiceStore.setState({
      choices: { u1: { credentialId: 'c1', model: 'claude-sonnet-5-5', effort: 'max' } },
    })
    const calls = stubApi({
      'POST /api/v1/projects/p-1/runs': {
        status: 202,
        body: { id: 'r-3', project_id: 'p-1', mode: 'build', status: 'queued' },
      },
    })
    const hook = setup()
    await act(async () => {
      await hook.result.current.mutateAsync('build')
    })
    // Список моделей ключа ещё не загружен: уровень не показан и не отправляется.
    expect(calls.at(-1)?.body).not.toHaveProperty('profile')
    hook.unmount()
    const known = setup({
      models: [
        {
          id: 'claude-sonnet-5-5',
          label: 'x',
          capabilities: { effort_levels: ['low', 'medium', 'high'], effort_default: 'high' },
        },
      ],
    })
    await act(async () => {
      await known.result.current.mutateAsync('build')
    })
    // «Максимум» эта модель не умеет: уходит показанный уровень по умолчанию.
    expect(calls.at(-1)?.body).toMatchObject({ profile: { effort: 'high' } })
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

describe('объектный запуск: диалог оценки и перестройка', () => {
  it('сохраняет выбранные ключ, модель, уровень, бюджет и голову перестройки', async () => {
    useModelChoiceStore.setState({
      choices: {
        u1: { credentialId: 'c1', model: 'claude-sonnet-5-5', effort: 'medium' },
      },
    })
    const calls = stubApi({
      'POST /api/v1/projects/p-1/runs': {
        status: 202,
        body: { id: 'r-4', project_id: 'p-1', mode: 'build', status: 'queued' },
      },
    })
    const hook = setup({
      models: [
        {
          id: 'claude-sonnet-5-5',
          label: 'x',
          capabilities: { effort_levels: ['low', 'medium', 'high'], effort_default: 'medium' },
        },
      ],
    })
    await act(async () => {
      await hook.result.current.mutateAsync({
        mode: 'build',
        replace_manual: true,
        base_version_id: 'v-1',
        budget: { cost_usd: 10, tokens: null },
      })
    })
    expect(calls.at(-1)?.body).toMatchObject({
      mode: 'build',
      replace_manual: true,
      base_version_id: 'v-1',
      credential_id: 'c1',
      model: 'claude-sonnet-5-5',
      profile: { effort: 'medium', budget: { cost_usd: 10, tokens: null } },
    })
  })
})
