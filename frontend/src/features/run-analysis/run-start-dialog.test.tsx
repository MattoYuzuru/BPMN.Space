import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { screen, waitFor } from '@testing-library/react'
import { stubApi } from '@/test/api-stub'
import { renderUi } from '@/test/render'
import { RunStartDialog } from './run-start-dialog'

vi.mock('@/features/model-picker/model-picker', () => ({
  ModelPicker: () => <span>Модель: Claude Opus 5.5</span>,
}))

const estimate = {
  calls: { min: 8, max: 12 },
  complete: true,
  cost: { currency: 'USD', min_usd: 1.8, max_usd: 3.2 },
  duration: { min_sec: 60, max_sec: 180 },
  breakdown: [
    {
      stage: 'reading_sources',
      label: 'Чтение источников',
      calls: { min: 2, max: 2 },
      tokens_in: { min: 1000, max: 1000 },
      tokens_out: { min: 100, max: 100 },
      cost: { currency: 'USD', min_usd: 0.2, max_usd: 0.4 },
    },
  ],
  tokens: { min: 120_000, max: 180_000 },
  notes: ['Калибровка: 2,0 знака на токен'],
  priced_on: '2026-10-06',
  model: 'claude-opus-5-5',
  provider: 'anthropic',
}

const run = {
  id: 'r1',
  project_id: 'p1',
  mode: 'analyze',
  status: 'queued',
  stage: null,
  stage_label: 'В очереди',
  progress: 0,
  started_at: '2026-11-04T10:00:00Z',
}

function mount() {
  const calls = stubApi({
    'POST /api/v1/projects/p1/runs/estimate': { body: estimate },
    'POST /api/v1/projects/p1/runs': { status: 202, body: run },
  })
  const onOpenChange = vi.fn()
  const rendered = renderUi(
    <QueryClientProvider client={new QueryClient()}>
      <RunStartDialog projectId="p1" mode="analyze" open onOpenChange={onOpenChange} />
    </QueryClientProvider>,
  )
  return { ...rendered, calls, onOpenChange }
}

const estimateCalls = (calls: ReturnType<typeof mount>['calls']) =>
  calls.filter((call) => call.path.endsWith('/estimate'))

afterEach(() => vi.unstubAllGlobals())

describe('диалог запуска с оценкой', () => {
  it('показывает диапазон денег, время, запросы, этапы и примечания', async () => {
    mount()
    expect(await screen.findByText(/\$1,8–3,2/)).toBeInTheDocument()
    expect(screen.getByText(/1–3\s+мин/)).toBeInTheDocument()
    expect(screen.getByText(/8–12\s+запросов/)).toBeInTheDocument()
    expect(screen.getByText(/120–180\s+тыс\.\s+токенов/)).toBeInTheDocument()
    expect(screen.getByText('Чтение источников')).toBeInTheDocument()
    expect(screen.getByText(/Калибровка: 2,0 знака/)).toBeInTheDocument()
    expect(screen.getByText(/Цены сверены/)).toBeInTheDocument()
  })

  it('помечает неполную оценку', async () => {
    stubApi({
      'POST /api/v1/projects/p1/runs/estimate': { body: { ...estimate, complete: false } },
    })
    renderUi(
      <QueryClientProvider client={new QueryClient()}>
        <RunStartDialog projectId="p1" mode="analyze" open onOpenChange={vi.fn()} />
      </QueryClientProvider>,
    )
    expect(await screen.findByText('Неполная')).toBeInTheDocument()
  })

  it('бюджет уходит в оценку и в запуск', async () => {
    const { user, calls } = mount()
    await screen.findByText(/\$1,8–3,2/)
    await user.type(screen.getByLabelText(/В долларах/), '10')
    await waitFor(() =>
      expect(
        estimateCalls(calls).some(
          (call) => (call.body as { profile?: { budget?: unknown } }).profile?.budget,
        ),
      ).toBe(true),
    )
    await user.click(screen.getByRole('button', { name: 'Запустить анализ' }))
    await waitFor(() =>
      expect(calls.some((call) => call.method === 'POST' && call.path.endsWith('/runs'))).toBe(
        true,
      ),
    )
    const start = calls.find((call) => call.method === 'POST' && call.path.endsWith('/runs'))
    expect(start?.body).toMatchObject({
      mode: 'analyze',
      replace_manual: false,
      profile: { budget: { cost_usd: 10, tokens: null } },
    })
  })

  it('переключение на сборку пересчитывает оценку с другим режимом', async () => {
    const { user, calls } = mount()
    await screen.findByText(/\$1,8–3,2/)
    await user.click(screen.getByRole('radio', { name: 'Сборка схемы' }))
    await waitFor(() =>
      expect(
        estimateCalls(calls).some((call) => (call.body as { mode?: string }).mode === 'build'),
      ).toBe(true),
    )
    expect(screen.getByRole('button', { name: 'Построить схему' })).toBeInTheDocument()
  })

  it('ошибку оценки объясняет и предлагает повторить', async () => {
    stubApi({
      'POST /api/v1/projects/p1/runs/estimate': {
        status: 422,
        body: { detail: 'Добавьте хотя бы один источник с текстом' },
      },
    })
    renderUi(
      <QueryClientProvider client={new QueryClient()}>
        <RunStartDialog projectId="p1" mode="analyze" open onOpenChange={vi.fn()} />
      </QueryClientProvider>,
    )
    expect(await screen.findByText('Оценку получить не удалось')).toBeInTheDocument()
    expect(screen.getByText(/Добавьте хотя бы один источник/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Повторить' })).toBeInTheDocument()
  })
})

describe('разбор бюджета в диалоге', () => {
  it('понимает разряды и копейки, отправляет оба лимита', async () => {
    const { user, calls } = mount()
    await screen.findByText(/\$1,8–3,2/)
    await user.type(screen.getByLabelText(/В долларах/), '1 000,50')
    await user.type(screen.getByLabelText(/В токенах/), '100 000')
    await waitFor(() =>
      expect(
        estimateCalls(calls).some(
          (call) =>
            JSON.stringify((call.body as { profile?: unknown }).profile) ===
            JSON.stringify({ budget: { cost_usd: 1000.5, tokens: 100000 } }),
        ),
      ).toBe(true),
    )
    await user.click(screen.getByRole('button', { name: 'Запустить анализ' }))
    await waitFor(() =>
      expect(calls.some((call) => call.method === 'POST' && call.path.endsWith('/runs'))).toBe(
        true,
      ),
    )
    const start = calls.find((call) => call.method === 'POST' && call.path.endsWith('/runs'))
    expect(start?.body).toMatchObject({
      profile: { budget: { cost_usd: 1000.5, tokens: 100000 } },
    })
  })

  it('мусор в поле — ошибка и выключенный запуск, без молчаливого усечения', async () => {
    const { user } = mount()
    await screen.findByText(/\$1,8–3,2/)
    await user.type(screen.getByLabelText(/В долларах/), '10abc')
    expect(await screen.findByText(/Введите сумму числом/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Запустить анализ' })).toBeDisabled()
    await user.clear(screen.getByLabelText(/В долларах/))
    await user.type(screen.getByLabelText(/В токенах/), '10,5')
    expect(await screen.findByText(/целое число токенов/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Запустить анализ' })).toBeDisabled()
  })
})
