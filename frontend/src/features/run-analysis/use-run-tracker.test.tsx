import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { type ProjectDetail, projectKeys } from '@/entities/project'
import type { Run, RunEvent } from '@/entities/run'
import { useRunStore } from '@/entities/run'
import { type OnboardingSignal, subscribeOnboardingSignals } from '@/shared/lib/onboarding-signals'
import { stubApi } from '@/test/api-stub'
import { RUN_POLL_MS, useRunTracker } from './use-run-tracker'

vi.mock('@/shared/ui', async (original) => ({
  ...(await original<typeof import('@/shared/ui')>()),
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn(), warning: vi.fn() }),
}))

/** Подменённый поток событий: тест сам присылает события и «теряет» связь. */
const stream = vi.hoisted(() => ({
  handlers: undefined as { onEvent: (event: RunEvent) => void; onLost?: () => void } | undefined,
  closed: 0,
  opened: [] as string[],
}))
vi.mock('@/entities/run/stream', () => ({
  retryDelay: () => 0,
  openRunStream: (id: string, handlers: NonNullable<typeof stream.handlers>) => {
    stream.handlers = handlers
    stream.opened.push(id)
    return () => {
      stream.closed += 1
    }
  },
}))

const run = (patch: Partial<Run> = {}): Run =>
  ({
    id: 'r-1',
    project_id: 'p-1',
    mode: 'build',
    status: 'running',
    stage: 'reading_sources',
    stage_label: 'Читаю источники',
    progress: 0,
    started_at: '2026-10-04T10:00:00Z',
    ...patch,
  }) as Run

const project = (patch: Partial<ProjectDetail> = {}) =>
  ({
    id: 'p-1',
    sources: [],
    questions: [
      { id: 'q-1', status: 'open' },
      { id: 'q-2', status: 'open' },
      { id: 'q-3', status: 'ignored' },
    ],
    latest_version: { id: 'v-1' },
    active_run: null,
    ...patch,
  }) as unknown as ProjectDetail

const signals: OnboardingSignal[] = []
let unsubscribe: () => void = () => {}

function setup(active: Run, detail: ProjectDetail = project()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(projectKeys.detail('p-1'), detail)
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  const initialProps: { projectId: string; active: Run | null } = { projectId: 'p-1', active }
  const hook = renderHook(
    ({ projectId, active }: { projectId: string; active: Run | null }) =>
      useRunTracker(projectId, active),
    { wrapper, initialProps },
  )
  return { client, ...hook }
}

const done = (patch: Partial<Run>): RunEvent => ({
  type: 'done',
  id: 10,
  data: { run: run({ status: 'succeeded', ...patch }) },
})

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  signals.length = 0
  stream.handlers = undefined
  stream.closed = 0
  stream.opened = []
  useRunStore.setState({ views: {}, expanded: {} })
  unsubscribe = subscribeOnboardingSignals((signal) => signals.push(signal))
})
afterEach(() => {
  unsubscribe()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('useRunTracker: сигналы обучения', () => {
  it.each(['succeeded', 'failed', 'cancelled'] as const)(
    'сохраняет поток до done со status=%s, если проект уже убрал active_run',
    async (status) => {
      const { rerender } = setup(run())
      act(() =>
        stream.handlers?.onEvent({
          type: 'stage',
          id: 1,
          data: { stage: 'reconciling', progress: 0.8, label: 'Сверяю вопросы' },
        }),
      )
      if (status === 'failed') {
        act(() => stream.handlers?.onEvent({ type: 'error', id: 2, data: { message: 'Сбой' } }))
      }
      rerender({ projectId: 'p-1', active: null })
      expect(stream.closed).toBe(0)
      expect(stream.opened).toEqual(['r-1'])
      expect(useRunStore.getState().views['p-1']?.stage).toBe('reconciling')
      await act(async () => {
        stream.handlers?.onEvent(done({ status }))
        await vi.advanceTimersByTimeAsync(10)
      })
      expect(useRunStore.getState().views['p-1']?.status).toBe(status)
      expect(stream.closed).toBe(1)
      expect(signals.filter((signal) => signal.type === 'run.finished')).toHaveLength(1)
    },
  )

  it('новый прогон заменяет старый поток, поздний done и onLost прежнего не меняют его', async () => {
    const calls = stubApi({
      'GET /api/v1/runs/r-1': () => ({ body: run({ status: 'succeeded' }) }),
    })
    const { rerender } = setup(run())
    const previous = stream.handlers
    rerender({ projectId: 'p-1', active: run({ id: 'r-2' }) })
    expect(stream.closed).toBe(1)
    expect(stream.opened).toEqual(['r-1', 'r-2'])
    await act(async () => {
      previous?.onEvent(done({}))
      previous?.onLost?.()
      await vi.advanceTimersByTimeAsync(RUN_POLL_MS + 10)
    })
    expect(useRunStore.getState().views['p-1']?.runId).toBe('r-2')
    expect(useRunStore.getState().views['p-1']?.status).toBe('running')
    expect(calls).toHaveLength(0)
    expect(signals.filter((signal) => signal.type === 'run.finished')).toHaveLength(0)
    rerender({ projectId: 'p-1', active: null })
    await act(async () => {
      stream.handlers?.onEvent(done({ id: 'r-2' }))
      await vi.advanceTimersByTimeAsync(10)
    })
    expect(stream.closed).toBe(2)
    expect(useRunStore.getState().views['p-1']?.status).toBe('succeeded')
    expect(signals.filter((signal) => signal.type === 'run.finished')).toHaveLength(1)
  })

  it('смена проекта закрывает поток, возврат восстанавливает незавершённый и не оживляет итог', async () => {
    const { rerender } = setup(run())
    const previous = stream.handlers
    rerender({ projectId: 'p-2', active: null })
    expect(stream.closed).toBe(1)
    expect(stream.opened).toEqual(['r-1'])
    act(() => previous?.onEvent(done({})))
    expect(useRunStore.getState().views['p-1']?.status).toBe('running')
    rerender({ projectId: 'p-1', active: null })
    expect(stream.opened).toEqual(['r-1', 'r-1'])
    await act(async () => {
      stream.handlers?.onEvent(done({}))
      await vi.advanceTimersByTimeAsync(10)
    })
    expect(stream.closed).toBe(2)
    rerender({ projectId: 'p-1', active: null })
    expect(stream.opened).toEqual(['r-1', 'r-1'])
  })

  it('подключение к идущему прогону не считается стартом: только статус', () => {
    setup(run())
    expect(signals).toEqual([{ type: 'run.status', status: 'running', projectId: 'p-1' }])
  })

  it('прогон в очереди: queued, затем running по первому этапу', () => {
    setup(run({ status: 'queued' }))
    expect(signals.at(-1)).toEqual({ type: 'run.status', status: 'queued', projectId: 'p-1' })
    act(() =>
      stream.handlers?.onEvent({
        type: 'stage',
        id: 1,
        data: { stage: 'extracting', progress: 0.2, label: 'Ищу' },
      } as RunEvent),
    )
    expect(signals.at(-1)).toEqual({ type: 'run.status', status: 'running', projectId: 'p-1' })
  })

  it('окончание: run.finished с числом открытых вопросов и признаком схемы', async () => {
    setup(run())
    signals.length = 0
    await act(async () => {
      stream.handlers?.onEvent(done({}))
      await vi.advanceTimersByTimeAsync(10)
    })
    expect(signals).toEqual([
      {
        type: 'run.finished',
        status: 'succeeded',
        openQuestions: 2,
        hasDiagram: true,
        projectId: 'p-1',
      },
    ])
  })

  it('упавший прогон без схемы: status failed, hasDiagram false', async () => {
    setup(run(), project({ latest_version: null, questions: [] }))
    signals.length = 0
    await act(async () => {
      stream.handlers?.onEvent(done({ status: 'failed' }))
      await vi.advanceTimersByTimeAsync(10)
    })
    expect(signals).toEqual([
      {
        type: 'run.finished',
        status: 'failed',
        openQuestions: 0,
        hasDiagram: false,
        projectId: 'p-1',
      },
    ])
  })

  it('окончание сообщается один раз', async () => {
    setup(run())
    signals.length = 0
    await act(async () => {
      stream.handlers?.onEvent(done({}))
      stream.handlers?.onEvent({ ...done({}), id: 11 })
      await vi.advanceTimersByTimeAsync(10)
    })
    expect(signals.filter((signal) => signal.type === 'run.finished')).toHaveLength(1)
  })

  it('потеря потока: раз в 5 с спрашиваем сервер, пока прогон не завершится', async () => {
    let status = 'running'
    const calls = stubApi({
      'GET /api/v1/runs/r-1': () => ({ body: run({ status: status as Run['status'] }) }),
    })
    const { rerender } = setup(run())
    signals.length = 0
    await act(async () => {
      stream.handlers?.onLost?.()
      rerender({ projectId: 'p-1', active: null })
      await vi.advanceTimersByTimeAsync(RUN_POLL_MS)
    })
    expect(calls.filter((call) => call.path === '/api/v1/runs/r-1')).toHaveLength(1)
    expect(signals).toEqual([])
    status = 'succeeded'
    await act(async () => {
      await vi.advanceTimersByTimeAsync(RUN_POLL_MS + 20)
    })
    expect(signals).toEqual([
      {
        type: 'run.finished',
        status: 'succeeded',
        openQuestions: 2,
        hasDiagram: true,
        projectId: 'p-1',
      },
    ])
    // Опрос остановился.
    const before = calls.length
    await act(async () => {
      await vi.advanceTimersByTimeAsync(RUN_POLL_MS * 3)
    })
    expect(calls.length).toBe(before)
    expect(useRunStore.getState().views['p-1']?.status).toBe('succeeded')
  })
})
