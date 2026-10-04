import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { type ProjectDetail, projectKeys } from '@/entities/project'
import { type OnboardingSignal, subscribeOnboardingSignals } from '@/shared/lib/onboarding-signals'
import { stubApi } from '@/test/api-stub'
import { useAddSampleSource, useAddTextSource } from './api'

vi.mock('@/shared/ui', async (original) => ({
  ...(await original<typeof import('@/shared/ui')>()),
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}))

function setup<T>(useHook: () => T) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  client.setQueryData(projectKeys.detail('p-1'), {
    id: 'p-1',
    sources: [],
  } as unknown as ProjectDetail)
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  return renderHook(useHook, { wrapper })
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

const source = (kind: string) => ({
  id: 's-1',
  project_id: 'p-1',
  kind,
  title: 'Источник',
  content: '',
  status: 'ready',
  active: true,
  created_at: '2026-10-04T10:00:00Z',
})

describe('сигнал source.added', () => {
  it('текст и голос — после ответа сервера, с видом источника', async () => {
    stubApi({
      'POST /api/v1/projects/p-1/sources/text': (call) => ({
        status: 201,
        body: source((call.body as { kind: string }).kind),
      }),
    })
    const hook = setup(() => useAddTextSource('p-1'))
    await act(async () => {
      await hook.result.current.mutateAsync({ kind: 'text', content: 'Текст процесса' })
    })
    await act(async () => {
      await hook.result.current.mutateAsync({
        kind: 'voice',
        content: 'Расшифровка',
        title: 'Голос',
      })
    })
    expect(signals).toEqual([
      { type: 'source.added', kind: 'text' },
      { type: 'source.added', kind: 'voice' },
    ])
  })

  it('пример из меню «Примеры» — тоже источник', async () => {
    stubApi({
      'POST /api/v1/projects/p-1/sources/sample': { status: 201, body: source('file') },
    })
    const hook = setup(() => useAddSampleSource('p-1'))
    await act(async () => {
      await hook.result.current.mutateAsync('tp861-meeting-note')
    })
    expect(signals).toEqual([{ type: 'source.added', kind: 'file' }])
  })

  it('отказ сервера — сигнала нет', async () => {
    stubApi({
      'POST /api/v1/projects/p-1/sources/sample': { status: 404, body: { detail: 'нет' } },
    })
    const hook = setup(() => useAddSampleSource('p-1'))
    await act(async () => {
      await hook.result.current.mutateAsync('нет').catch(() => undefined)
    })
    expect(signals).toEqual([])
  })
})
