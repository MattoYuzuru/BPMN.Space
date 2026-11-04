import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { type OnboardingSignal, subscribeOnboardingSignals } from '@/shared/lib/onboarding-signals'
import { stubApi } from '@/test/api-stub'
import { useCreateShareLink } from './api'

vi.mock('@/shared/ui', async (original) => ({
  ...(await original<typeof import('@/shared/ui')>()),
  toast: Object.assign(vi.fn(), { error: vi.fn() }),
}))

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

function setup() {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  return renderHook(() => useCreateShareLink('p-1'), { wrapper })
}

describe('сигнал share.created', () => {
  it('приходит после создания ссылки на сервере', async () => {
    stubApi({
      'POST /api/v1/projects/p-1/share-links': {
        status: 201,
        body: { id: 'l-1', role: 'viewer', url_path: '/share/abc', expires_at: null },
      },
    })
    const hook = setup()
    await act(async () => {
      await hook.result.current.mutateAsync({ role: 'viewer', days: 30 })
    })
    expect(signals).toEqual([{ type: 'share.created' }])
  })

  it('ссылка проверки сообщает и о создании ссылки, и о проверке; lane_ids уходят', async () => {
    const calls = stubApi({
      'POST /api/v1/projects/p-1/share-links': {
        status: 201,
        body: {
          id: 'l-2',
          role: 'reviewer',
          url_path: '/share/rev',
          expires_at: null,
          lane_ids: ['Lane_1'],
        },
      },
    })
    const hook = setup()
    await act(async () => {
      await hook.result.current.mutateAsync({
        role: 'reviewer',
        days: 30,
        laneIds: ['Продажи'],
      })
    })
    expect(signals).toEqual([{ type: 'share.created' }, { type: 'share.reviewer.created' }])
    expect(calls.find((call) => call.method === 'POST')?.body).toEqual({
      role: 'reviewer',
      expires_in_days: 30,
      lane_ids: ['Продажи'],
    })
  })

  it('просмотру lane_ids не отправляются и сигнала проверки нет', async () => {
    const calls = stubApi({
      'POST /api/v1/projects/p-1/share-links': {
        status: 201,
        body: { id: 'l-3', role: 'viewer', url_path: '/share/v', expires_at: null },
      },
    })
    const hook = setup()
    await act(async () => {
      await hook.result.current.mutateAsync({ role: 'viewer', days: 30, laneIds: ['Продажи'] })
    })
    expect(signals).toEqual([{ type: 'share.created' }])
    expect(calls.find((call) => call.method === 'POST')?.body).toEqual({
      role: 'viewer',
      expires_in_days: 30,
    })
  })

  it('отказ сервера — сигнала нет', async () => {
    stubApi({
      'POST /api/v1/projects/p-1/share-links': { status: 403, body: { detail: 'нельзя' } },
    })
    const hook = setup()
    await act(async () => {
      await hook.result.current.mutateAsync({ role: 'viewer', days: 30 }).catch(() => undefined)
    })
    expect(signals).toEqual([])
  })
})
