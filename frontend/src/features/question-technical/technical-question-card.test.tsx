import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { screen, waitFor, within } from '@testing-library/react'
import type { Question } from '@/entities/question'
import { subscribeOnboardingSignals } from '@/shared/lib/onboarding-signals'
import { TooltipProvider } from '@/shared/ui'
import { stubApi } from '@/test/api-stub'
import { renderUi } from '@/test/render'
import { TechnicalQuestionCard } from './technical-question-card'

const question: Question = {
  id: 'q1',
  project_id: 'p1',
  code: 'TQ-1',
  kind: 'budget_reached',
  severity: 'major',
  status: 'open',
  text: 'Бюджет прогона $10 исчерпан на этапе сверки вопросов.',
  assumption: '',
  element_ids: [],
  category: 'technical',
  blocking: true,
  actions: [
    { kind: 'raise_budget', label: 'Поднять бюджет' },
    { kind: 'continue_without', label: 'Продолжить без этого' },
    { kind: 'retry', label: 'Повторить' },
    { kind: 'open_settings', label: 'Открыть настройки' },
  ],
  created_at: '2026-11-04T10:00:00Z',
  updated_at: '2026-11-04T10:00:00Z',
}

function mount(
  onOpenSettings = vi.fn(),
  budget?: { cost_usd?: number | null; tokens?: number | null } | null,
) {
  const calls = stubApi({
    'POST /api/v1/questions/q1/actions': (call) => ({
      body: {
        ...question,
        status:
          (call.body as { action: string }).action === 'continue_without' ? 'ignored' : 'resolved',
      },
    }),
  })
  const rendered = renderUi(
    <QueryClientProvider client={new QueryClient()}>
      <TooltipProvider>
        <TechnicalQuestionCard
          question={question}
          projectId="p1"
          budget={budget}
          onOpenSettings={onOpenSettings}
        />
      </TooltipProvider>
    </QueryClientProvider>,
  )
  return { ...rendered, calls, onOpenSettings }
}

afterEach(() => vi.unstubAllGlobals())

describe('карточка технического вопроса', () => {
  it('показывает суть, тип и блокировку прогона', () => {
    mount()
    expect(screen.getByLabelText('Технический вопрос TQ-1')).toBeInTheDocument()
    expect(screen.getByText('Исчерпан бюджет')).toBeInTheDocument()
    expect(screen.getByText(/Бюджет прогона \$10 исчерпан/)).toBeInTheDocument()
    expect(screen.getByText('Блокирует прогон')).toBeInTheDocument()
  })

  it('«Повторить» отправляет действие и публикует сигнал обучения', async () => {
    const signals: string[] = []
    const unsubscribe = subscribeOnboardingSignals((signal) => {
      if (signal.type === 'question.technical.resolved') signals.push(signal.action)
    })
    const { user, calls } = mount()
    await user.click(screen.getByRole('button', { name: 'Повторить' }))
    await waitFor(() => expect(calls.some((call) => call.method === 'POST')).toBe(true))
    expect(calls.find((call) => call.method === 'POST')?.body).toEqual({
      action: 'retry',
      budget: null,
    })
    await waitFor(() => expect(signals).toContain('retry'))
    unsubscribe()
  })

  it('«Открыть настройки» — переход без серверного действия', async () => {
    const { user, calls, onOpenSettings } = mount()
    await user.click(screen.getByRole('button', { name: 'Открыть настройки' }))
    expect(onOpenSettings).toHaveBeenCalledOnce()
    expect(calls.some((call) => call.method === 'POST')).toBe(false)
  })

  it('«Поднять бюджет» спрашивает новый лимит и отправляет его', async () => {
    const { user, calls } = mount()
    await user.click(screen.getByRole('button', { name: 'Поднять бюджет' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText(/В долларах/), '15')
    await user.click(within(dialog).getByRole('button', { name: 'Поднять бюджет' }))
    await waitFor(() => expect(calls.some((call) => call.method === 'POST')).toBe(true))
    expect(calls.find((call) => call.method === 'POST')?.body).toEqual({
      action: 'raise_budget',
      budget: { cost_usd: 15, tokens: null },
    })
  })
})

it('показывает текущий бюджет и не позволяет снять токеновый лимит', async () => {
  const { user, calls } = mount(vi.fn(), { cost_usd: 10, tokens: 200_000 })
  await user.click(screen.getByRole('button', { name: 'Поднять бюджет' }))
  const dialog = await screen.findByRole('dialog')
  expect(within(dialog).getByText(/Сейчас: \$10 и 200\s+тыс\. токенов/)).toBeInTheDocument()
  const cost = within(dialog).getByLabelText(/В долларах/)
  const tokens = within(dialog).getByLabelText(/В токенах/)
  expect(cost).toHaveValue('10')
  expect(tokens).toHaveValue('200000')
  await user.clear(cost)
  await user.type(cost, '5')
  expect(within(dialog).getByText(/Не меньше текущего/)).toBeInTheDocument()
  expect(within(dialog).getByRole('button', { name: 'Поднять бюджет' })).toBeDisabled()
  await user.clear(cost)
  await user.type(cost, '15')
  await user.click(within(dialog).getByRole('button', { name: 'Поднять бюджет' }))
  await waitFor(() => expect(calls.some((call) => call.method === 'POST')).toBe(true))
  expect(calls.find((call) => call.method === 'POST')?.body).toEqual({
    action: 'raise_budget',
    budget: { cost_usd: 15, tokens: 200_000 },
  })
})
