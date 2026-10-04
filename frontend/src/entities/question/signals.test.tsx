import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { type ProjectDetail, projectKeys } from '@/entities/project'
import { type OnboardingSignal, subscribeOnboardingSignals } from '@/shared/lib/onboarding-signals'
import { stubApi } from '@/test/api-stub'
import { useQuestionAction } from './api'
import type { Question } from './model'

vi.mock('@/shared/ui', async (original) => ({
  ...(await original<typeof import('@/shared/ui')>()),
  toast: Object.assign(vi.fn(), { error: vi.fn() }),
}))

const question = {
  id: 'q-1',
  project_id: 'p-1',
  code: 'Q-1',
  status: 'open',
  text: 'Кто согласует?',
  element_ids: [],
  created_at: '2026-10-01T10:00:00Z',
  updated_at: '2026-10-01T10:00:00Z',
} as unknown as Question

function setup() {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
  client.setQueryData(projectKeys.detail('p-1'), {
    id: 'p-1',
    questions: [question],
    summary: { resolved: 0, open: 1, new: 0, ignored: 0, answered: 0 },
  } as unknown as ProjectDetail)
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  return renderHook(() => useQuestionAction('p-1'), { wrapper })
}

const signals: OnboardingSignal[] = []
let unsubscribe: () => void = () => {}
beforeEach(() => {
  signals.length = 0
  unsubscribe = subscribeOnboardingSignals((signal) => signals.push(signal))
})
afterEach(() => {
  unsubscribe()
  vi.unstubAllGlobals()
})

describe('сигналы обучения от действий с вопросом', () => {
  it('ответ: сигнал только после ответа сервера, не при оптимистичном обновлении', async () => {
    let release: () => void = () => {}
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input instanceof Request ? input.url : input)
        if (url.endsWith('/auth/csrf')) {
          return new Response(JSON.stringify({ csrf_token: 't' }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          })
        }
        await gate
        return new Response(JSON.stringify({ ...question, status: 'answered' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }),
    )
    const hook = setup()
    act(() =>
      hook.result.current.mutate({ question, action: { type: 'answer', text: 'Финотдел' } }),
    )
    // Карточка уже «отвечена» оптимистично, но сервер ещё не ответил.
    await waitFor(() => expect(hook.result.current.isPending).toBe(true))
    expect(signals).toEqual([])
    release()
    await waitFor(() => expect(hook.result.current.isSuccess).toBe(true))
    expect(signals).toEqual([{ type: 'question.answered', id: 'q-1' }])
  })

  it('ошибка сервера — сигнала нет', async () => {
    stubApi({ 'POST /api/v1/questions/q-1/answer': { status: 409, body: { detail: 'решён' } } })
    const hook = setup()
    await act(async () => {
      hook.result.current.mutate({ question, action: { type: 'answer', text: 'Финотдел' } })
    })
    await waitFor(() => expect(hook.result.current.isError).toBe(true))
    expect(signals).toEqual([])
  })

  it('игнор — question.ignored, возврат в открытые — ничего', async () => {
    stubApi({
      'POST /api/v1/questions/q-1/ignore': { body: { ...question, status: 'ignored' } },
      'POST /api/v1/questions/q-1/reopen': { body: { ...question, status: 'open' } },
    })
    const hook = setup()
    await act(async () => {
      await hook.result.current.mutateAsync({ question, action: { type: 'ignore' } })
    })
    expect(signals).toEqual([{ type: 'question.ignored', id: 'q-1' }])
    await act(async () => {
      await hook.result.current.mutateAsync({ question, action: { type: 'reopen' } })
    })
    expect(signals).toHaveLength(1)
  })
})
