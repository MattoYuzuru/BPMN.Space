import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { domAnimation, LazyMotion } from 'motion/react'
import { type Run, type RunEvent, STAGES, useRunStore } from '@/entities/run'
import { subscribeOnboardingSignals } from '@/shared/lib/onboarding-signals'
import { TooltipProvider } from '@/shared/ui'
import { stubApi } from '@/test/api-stub'
import { RunProgress } from './run-progress'
import { STAGE_VISIBLE_MS, SUMMARY_VISIBLE_MS } from './use-run-presentation'

const motion = vi.hoisted(() => ({ reduced: false }))
vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => motion.reduced,
}))

const run = (patch: Partial<Run> = {}): Run => ({
  id: 'r-1',
  project_id: 'p-1',
  mode: 'build',
  status: 'queued',
  stage: null,
  stage_label: 'В очереди',
  progress: 0,
  started_at: new Date(0).toISOString(),
  ...patch,
})

function mount(projectId = 'p-1') {
  const client = new QueryClient()
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <LazyMotion features={domAnimation}>
          <RunProgress projectId={projectId} />
        </LazyMotion>
      </TooltipProvider>
    </QueryClientProvider>,
  )
}

function finish(patch: Partial<Run> = {}) {
  const store = useRunStore.getState()
  const mode = store.views['p-1']?.mode ?? 'build'
  act(() => {
    for (const [index, stage] of STAGES[mode].entries()) {
      store.apply('p-1', {
        type: 'stage',
        id: index + 1,
        data: { stage, label: stage, progress: index / STAGES[mode].length },
      } as RunEvent)
    }
    store.apply('p-1', {
      type: 'done',
      id: 10,
      data: {
        run: run({ mode, status: 'succeeded', finished_at: new Date(100).toISOString(), ...patch }),
      },
    })
  })
}

async function tick(ms: number) {
  await act(async () => vi.advanceTimersByTimeAsync(ms))
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(0)
  motion.reduced = false
  useRunStore.setState({ views: {}, expanded: {}, presented: {} })
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

it('мгновенная сборка завершает все шесть этапов, затем показывает итог полные 2,5 с', async () => {
  useRunStore.getState().track(run())
  mount()
  finish()
  // Данные готовы немедленно; очередь касается только видимой карточки.
  expect(useRunStore.getState().views['p-1']?.status).toBe('succeeded')
  expect(useRunStore.getState().views['p-1']?.finishedAt).toBe(100)
  await tick(0)
  for (const stage of [
    'Читаю источники',
    'Ищу участников и шаги',
    'Сверяю вопросы',
    'Строю структуру процесса',
    'Проверяю схему',
    'Раскладываю схему',
  ]) {
    expect(
      screen.getByRole('list', { name: 'Этапы прогона' }).querySelector('[aria-current="step"]'),
    ).toHaveTextContent(stage)
    await tick(STAGE_VISIBLE_MS)
  }
  expect(screen.getByText('Схема построена')).toBeInTheDocument()
  await tick(SUMMARY_VISIBLE_MS - 1)
  expect(useRunStore.getState().expanded['p-1']).toBe(true)
  await tick(1)
  expect(useRunStore.getState().expanded['p-1']).toBe(false)
  expect(useRunStore.getState().presented['p-1']).toBe('r-1')
})

it.each(['failed', 'cancelled'] as const)(
  'показывает %s сразу и не скрывает как успешный результат',
  async (status) => {
    useRunStore.getState().track(run())
    mount()
    finish({ status, error: 'Остановлено' })
    expect(
      screen.getByText(status === 'failed' ? 'Прогон остановлен' : 'Прогон отменён'),
    ).toBeInTheDocument()
    expect(screen.queryByText('Схема построена')).not.toBeInTheDocument()
    await tick(10_000)
    expect(useRunStore.getState().expanded['p-1']).toBe(true)
  },
)

it('при сокращённом движении сразу показывает итог, но сохраняет время чтения', async () => {
  motion.reduced = true
  useRunStore.getState().track(run())
  mount()
  finish()
  expect(screen.getByText('Схема построена')).toBeInTheDocument()
  expect(screen.queryByRole('list', { name: 'Этапы прогона' })).not.toBeInTheDocument()
  await tick(SUMMARY_VISIBLE_MS - 1)
  expect(useRunStore.getState().expanded['p-1']).toBe(true)
  await tick(1)
  expect(useRunStore.getState().expanded['p-1']).toBe(false)
})

it('старый итоговый таймер не скрывает новый прогон', async () => {
  motion.reduced = true
  useRunStore.getState().track(run())
  mount()
  finish()
  await tick(2000)
  act(() => useRunStore.getState().track(run({ id: 'r-2' })))
  await tick(1000)
  expect(useRunStore.getState().expanded['p-1']).toBe(true)
  expect(useRunStore.getState().views['p-1']?.runId).toBe('r-2')
  expect(useRunStore.getState().presented['p-1']).not.toBe('r-2')
})

it('ручное закрытие завершает показ; повторное открытие не проигрывает этапы', () => {
  useRunStore.getState().track(run())
  mount()
  finish()
  const signals: string[] = []
  const unsubscribe = subscribeOnboardingSignals((signal) => signals.push(signal.type))
  fireEvent.click(screen.getByRole('button', { name: 'Скрыть' }))
  expect(useRunStore.getState().presented['p-1']).toBe('r-1')
  expect(signals).toContain('run.presented')
  act(() => useRunStore.getState().setExpanded('p-1', true))
  expect(screen.getByText('Схема построена')).toBeInTheDocument()
  unsubscribe()
})

it('исторический завершённый прогон открывается сразу как итог', () => {
  useRunStore.getState().track(run({ status: 'succeeded' }))
  mount()
  expect(screen.getByText('Схема построена')).toBeInTheDocument()
  expect(screen.queryByRole('list', { name: 'Этапы прогона' })).not.toBeInTheDocument()
})

it('свёрнутая во время работы карточка открывается сразу с итогом', () => {
  useRunStore.getState().track(run())
  mount()
  act(() => useRunStore.getState().setExpanded('p-1', false))
  finish()
  act(() => useRunStore.getState().setExpanded('p-1', true))
  expect(screen.getByText('Схема построена')).toBeInTheDocument()
  expect(screen.queryByRole('list', { name: 'Этапы прогона' })).not.toBeInTheDocument()
})

it('свой запуск с уже готовым HTTP-ответом всё равно показывает этапы', () => {
  useRunStore.getState().track(run({ status: 'succeeded' }), true)
  mount()
  expect(screen.getByRole('list', { name: 'Этапы прогона' })).toBeInTheDocument()
  expect(screen.queryByText('Схема построена')).not.toBeInTheDocument()
})

it('переключение проекта снимает таймер карточки прошлого проекта', async () => {
  motion.reduced = true
  useRunStore.getState().track(run())
  const panel = mount()
  finish()
  panel.unmount()
  useRunStore.getState().track(run({ id: 'r-other', project_id: 'p-other' }))
  mount('p-other')
  await tick(5000)
  expect(useRunStore.getState().expanded['p-other']).toBe(true)
  expect(useRunStore.getState().expanded['p-1']).toBe(true)
})

describe('стоимость и ожидание технического вопроса', () => {
  const cost = {
    calls: 8,
    tokens_in: 120_000,
    tokens_out: 14_000,
    cache_read_tokens: 40_000,
    cache_write_tokens: 9_000,
    cost_usd: 2.71,
    complete: true,
    currency: 'USD' as const,
    by_stage: [
      {
        stage: 'reading_sources',
        label: 'Чтение источников',
        calls: 8,
        tokens_in: 120_000,
        tokens_out: 14_000,
        cache_read_tokens: 40_000,
        cache_write_tokens: 9_000,
        cost_usd: 2.71,
      },
    ],
  }

  it('показывает потраченное и бюджет, разбивку по этапам', async () => {
    useRunStore.getState().track(
      run({
        status: 'running',
        cost,
        profile: { budget: { cost_usd: 10, tokens: null } },
      }),
    )
    mount()
    await tick(0)
    const block = screen.getByTestId('run-cost')
    expect(block).toBeInTheDocument()
    expect(within(block).getAllByText(/\$2,71/).length).toBeGreaterThan(0)
    expect(screen.getByText(/из \$10/)).toBeInTheDocument()
    expect(screen.getByText(/134\s+тыс\.\s+токенов · 8 вызовов/)).toBeInTheDocument()
    expect(screen.getByText('По этапам')).toBeInTheDocument()
  })

  it('в ожидании показывает «Продолжить» и возобновляет прогон', async () => {
    const calls = stubApi({
      'POST /api/v1/runs/r-1/resume': { body: run({ status: 'queued' }) },
    })
    useRunStore.getState().track(run({ status: 'waiting', stage_label: 'Ждёт вашего действия' }))
    mount()
    await tick(0)
    expect(screen.getByText('Ждёт вашего действия')).toBeInTheDocument()
    expect(screen.getByText(/Прогон остановился на техническом вопросе/)).toBeInTheDocument()
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Продолжить' }))
      await Promise.resolve()
    })
    expect(calls.some((call) => call.path.endsWith('/resume'))).toBe(true)
    expect(useRunStore.getState().views['p-1']?.status).toBe('running')
  })
})

it('агентный прогон показывает бейдж режима и реальное число ходов', async () => {
  useRunStore.getState().track(
    run({
      status: 'running',
      stage: 'reading_sources',
      stage_label: 'Агентное чтение',
      profile: { mode: 'agent', max_steps: 12 },
      cost: {
        tokens_in: 800,
        tokens_out: 400,
        cache_read_tokens: 0,
        cache_write_tokens: 0,
        calls: 3,
        cost_usd: 1,
        complete: true,
        currency: 'USD' as const,
        by_stage: [
          {
            stage: 'agent',
            label: 'Агентное чтение',
            calls: 3,
            tokens_in: 800,
            tokens_out: 400,
            cache_read_tokens: 0,
            cache_write_tokens: 0,
            cost_usd: 1,
          },
        ],
      },
    }),
  )
  mount()
  await tick(0)
  expect(screen.getByText('Агентный режим')).toBeInTheDocument()
  expect(screen.getByTestId('run-agent-steps')).toHaveTextContent('Ходов агента: 3 из 12')
})
