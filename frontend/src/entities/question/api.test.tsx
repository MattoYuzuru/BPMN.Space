import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { type ProjectDetail, projectKeys } from '@/entities/project'
import { useQuestionAction } from './api'
import type { Question } from './model'

const toastError = vi.fn()
vi.mock('@/shared/ui', async (original) => ({
  ...(await original<typeof import('@/shared/ui')>()),
  toast: Object.assign(vi.fn(), { error: (...args: unknown[]) => toastError(...args) }),
}))

const question: Question = {
  id: 'q-1',
  project_id: 'p-1',
  code: 'Q-1',
  kind: 'missing_actor',
  severity: 'major',
  status: 'open',
  text: 'Кто согласует бюджет?',
  assumption: 'Руководитель отдела',
  element_ids: [],
  created_at: '2026-10-01T10:00:00Z',
  updated_at: '2026-10-01T10:00:00Z',
}

const project = {
  id: 'p-1',
  title: 'Проект',
  questions: [question],
  summary: { resolved: 0, open: 1, new: 0, ignored: 0, answered: 0 },
} as unknown as ProjectDetail

function setup() {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
  client.setQueryData(projectKeys.detail('p-1'), project)
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  const hook = renderHook(() => useQuestionAction('p-1'), { wrapper })
  const status = () =>
    client.getQueryData<ProjectDetail>(projectKeys.detail('p-1'))?.questions[0]?.status
  return { client, hook, status }
}

/** Ответ fetch, который тест отпускает вручную, — чтобы увидеть оптимистичное состояние. */
function deferredFetch() {
  let release: (response: Response) => void = () => {}
  const pending = new Promise<Response>((resolve) => {
    release = resolve
  })
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      if (String(input).includes('/auth/csrf')) {
        return Promise.resolve(
          new Response(JSON.stringify({ csrf_token: 'csrf-test-token' }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }),
        )
      }
      return pending
    }),
  )
  return (status: number, body: unknown) =>
    release(
      new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
}

afterEach(() => {
  vi.unstubAllGlobals()
  toastError.mockReset()
})

describe('useQuestionAction', () => {
  it('сразу переводит вопрос в «допущение», а ответ сервера подтверждает', async () => {
    const respond = deferredFetch()
    const { hook, status, client } = setup()
    act(() => hook.result.current.mutate({ question, action: { type: 'ignore' } }))
    await waitFor(() => expect(status()).toBe('ignored'))
    expect(client.getQueryData<ProjectDetail>(projectKeys.detail('p-1'))?.summary.ignored).toBe(1)
    respond(200, { ...question, status: 'ignored' })
    await waitFor(() => expect(hook.result.current.isSuccess).toBe(true))
    expect(status()).toBe('ignored')
  })

  it('откатывает и показывает ошибку, если сервер отказал', async () => {
    const respond = deferredFetch()
    const { hook, status } = setup()
    act(() =>
      hook.result.current.mutate({ question, action: { type: 'answer', text: 'Финотдел' } }),
    )
    await waitFor(() => expect(status()).toBe('answered'))
    respond(409, { detail: 'Вопрос уже решён' })
    await waitFor(() => expect(hook.result.current.isError).toBe(true))
    expect(status()).toBe('open')
    expect(toastError).toHaveBeenCalledWith(
      'Ответ не сохранён',
      expect.objectContaining({ description: 'Вопрос уже решён' }),
    )
  })
})
