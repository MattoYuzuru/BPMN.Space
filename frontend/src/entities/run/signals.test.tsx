import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { type ProjectDetail, projectKeys } from '@/entities/project'
import { type OnboardingSignal, subscribeOnboardingSignals } from '@/shared/lib/onboarding-signals'
import { stubApi } from '@/test/api-stub'
import { useStartRun } from './api'

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
  client.setQueryData(projectKeys.detail('p-1'), { id: 'p-1', status: 'empty' } as ProjectDetail)
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  return renderHook(() => useStartRun('p-1'), { wrapper })
}

describe('сигнал run.started', () => {
  it('приходит только при реальном запуске прогона, с проектом', async () => {
    stubApi({
      'POST /api/v1/projects/p-1/runs': {
        status: 202,
        body: { id: 'r-1', project_id: 'p-1', mode: 'build', status: 'queued' },
      },
    })
    const hook = setup()
    await act(async () => {
      await hook.result.current.mutateAsync('build')
    })
    expect(signals).toEqual([{ type: 'run.started', id: 'r-1', projectId: 'p-1' }])
  })

  it('отказ сервера (409) — сигнала нет', async () => {
    stubApi({ 'POST /api/v1/projects/p-1/runs': { status: 409, body: { detail: 'Уже идёт' } } })
    const hook = setup()
    await act(async () => {
      await hook.result.current.mutateAsync('build').catch(() => undefined)
    })
    expect(signals).toEqual([])
  })
})
