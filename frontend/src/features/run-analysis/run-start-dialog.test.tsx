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

const capabilities = (tools: boolean) => ({
  accepts_temperature: true,
  context_tokens: 200_000,
  effort_default: 'medium' as const,
  effort_levels: ['low', 'medium', 'high'] as ('low' | 'medium' | 'high')[],
  known: true,
  max_output_tokens: 32_000,
  pdf_input: true,
  prices: {
    input: 4,
    output: 20,
    cache_read: 0.2,
    cache_write: 5,
    checked_on: '2026-10-06',
  },
  tools,
  vision: true,
})

const credential = {
  id: 'c1',
  label: 'Рабочий',
  provider: 'anthropic',
  is_default: true,
  default_model: 'claude-opus-5-5',
  base_url: null,
  key_hint: 'abcd',
  created_at: '2026-11-01T10:00:00Z',
  last_error: null,
  last_used_at: null,
}

function mount(
  overrides: Record<string, Parameters<typeof stubApi>[0][string]> = {},
  opts: { tools?: boolean } = {},
) {
  const calls = stubApi({
    'GET /api/v1/auth/session': {
      body: { auth_enabled: true, user: { id: 'u1', email: 'u@example.com' } },
    },
    'GET /api/v1/me/llm-credentials': { body: { items: [credential] } },
    'GET /api/v1/me/llm-credentials/c1/models': {
      body: {
        items: [
          {
            id: 'claude-opus-5-5',
            label: 'Claude Opus 5.5',
            capabilities: capabilities(opts.tools ?? true),
          },
        ],
      },
    },
    'POST /api/v1/projects/p1/runs/estimate': { body: estimate },
    'POST /api/v1/projects/p1/runs': { status: 202, body: run },
    ...overrides,
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

  it('агентный режим недоступен для модели без инструментов', async () => {
    mount({}, { tools: false })
    await waitFor(() => expect(screen.getByRole('radio', { name: /Агентный/ })).toBeDisabled())
    expect(await screen.findByText(/не поддерживает инструменты/)).toBeInTheDocument()
  })

  it('агентный режим уходит в оценку и в запуск с лимитом шагов', async () => {
    const { user, calls } = mount()
    await waitFor(() => expect(screen.getByRole('radio', { name: /Агентный/ })).toBeEnabled())
    await user.click(screen.getByRole('radio', { name: /Агентный/ }))
    const steps = screen.getByLabelText(/Лимит шагов/)
    await user.clear(steps)
    await user.type(steps, '16')
    expect(screen.getByText(/агент сам читает|Агентный — модель сама/)).toBeInTheDocument()
    await waitFor(() =>
      expect(
        estimateCalls(calls).some(
          (call) =>
            (call.body as { profile?: { mode?: string; max_steps?: number } }).profile?.mode ===
              'agent' &&
            (call.body as { profile?: { max_steps?: number } }).profile?.max_steps === 16,
        ),
      ).toBe(true),
    )
    await user.click(screen.getByRole('button', { name: 'Запустить анализ' }))
    await waitFor(() =>
      expect(calls.some((call) => call.method === 'POST' && call.path.endsWith('/runs'))).toBe(
        true,
      ),
    )
    expect(
      calls.find((call) => call.method === 'POST' && call.path.endsWith('/runs'))?.body,
    ).toMatchObject({
      mode: 'analyze',
      profile: { mode: 'agent', max_steps: 16 },
    })
  })

  it('неверный лимит шагов выключает запуск', async () => {
    const { user } = mount()
    await waitFor(() => expect(screen.getByRole('radio', { name: /Агентный/ })).toBeEnabled())
    await user.click(screen.getByRole('radio', { name: /Агентный/ }))
    const steps = screen.getByLabelText(/Лимит шагов/)
    await user.clear(steps)
    await user.type(steps, '0')
    expect(screen.getByRole('button', { name: 'Запустить анализ' })).toBeDisabled()
    expect(screen.getByText(/целое число от 1 до 200/)).toBeInTheDocument()
  })

  it('отказ сервера 422 объясняет причину агентного режима', async () => {
    const { user } = mount({
      'POST /api/v1/projects/p1/runs': {
        status: 422,
        body: { detail: 'Агентный режим выключен: LLM_AGENT_MODE' },
      },
    })
    await waitFor(() => expect(screen.getByRole('radio', { name: /Агентный/ })).toBeEnabled())
    await user.click(screen.getByRole('radio', { name: /Агентный/ }))
    await user.click(screen.getByRole('button', { name: 'Запустить анализ' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/не разрешил агентный режим/)
    expect(screen.getByRole('alert')).toHaveTextContent(/LLM_AGENT_MODE/)
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
