import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { Schemas } from '@/shared/api/client'
import { TooltipProvider } from '@/shared/ui'
import { stubApi } from '@/test/api-stub'
import { renderUi } from '@/test/render'
import { ReviewAnswers } from './review-answers'

const question = (patch: Partial<Schemas['Question']> = {}): Schemas['Question'] =>
  ({
    id: 'q1',
    project_id: 'p1',
    code: 'Q-1',
    text: 'Кто согласует заявку?',
    assumption: 'Согласует диспетчер',
    severity: 'major',
    status: 'open',
    category: 'business',
    kind: 'business',
    blocking: false,
    element_ids: [],
    created_at: '2026-11-04T10:00:00Z',
    updated_at: '2026-11-04T10:00:00Z',
    actions: [],
    ...patch,
  }) as Schemas['Question']

const answered: Schemas['Answer'] = {
  source_id: '00000000-0000-0000-0000-000000000001',
  text: 'Согласует главный инженер',
  via: 'review',
  via_name: 'Закупка · rev-1234',
  share_link_id: '00000000-0000-0000-0000-000000000002',
}

function mount() {
  const user = userEvent.setup()
  renderUi(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <TooltipProvider>
        <ReviewAnswers token="tok" />
      </TooltipProvider>
    </QueryClientProvider>,
  )
  return { user }
}

afterEach(() => vi.unstubAllGlobals())

it('отправляет ответ по ссылке и скрывает форму после успеха', async () => {
  let sent = false
  const calls = stubApi({
    'GET /api/v1/shares/tok/questions': () => ({
      body: [sent ? question({ status: 'answered', answer: answered }) : question()],
    }),
    'POST /api/v1/shares/tok/questions/q1/answer': (call) => {
      sent = true
      return {
        body: question({
          status: 'answered',
          answer: { ...answered, text: (call.body as { text: string }).text },
        }),
      }
    },
  })
  const { user } = mount()
  expect(await screen.findByText('Кто согласует заявку?')).toBeInTheDocument()
  const field = screen.getByLabelText('Ответ на вопрос Q-1')
  await user.type(field, '  Согласует главный инженер  ')
  await user.click(screen.getByRole('button', { name: 'Отправить ответ' }))
  await waitFor(() => expect(calls.some((call) => call.method === 'POST')).toBe(true))
  expect(calls.find((call) => call.method === 'POST')?.body).toEqual({
    text: 'Согласует главный инженер',
  })
  await waitFor(() => expect(screen.queryByLabelText('Ответ на вопрос Q-1')).toBeNull())
})

it('пустой ответ не отправляет запрос и объясняет почему', async () => {
  const calls = stubApi({ 'GET /api/v1/shares/tok/questions': { body: [question()] } })
  const { user } = mount()
  await screen.findByText('Кто согласует заявку?')
  await user.click(screen.getByRole('button', { name: 'Отправить ответ' }))
  expect(screen.getByText(/Напишите ответ/)).toBeInTheDocument()
  expect(calls.some((call) => call.method === 'POST')).toBe(false)
})

it('404 объясняет, что вопрос вне области проверки', async () => {
  stubApi({
    'GET /api/v1/shares/tok/questions': { body: [question()] },
    'POST /api/v1/shares/tok/questions/q1/answer': {
      status: 404,
      body: { detail: 'Вопрос не найден' },
    },
  })
  const { user } = mount()
  await screen.findByText('Кто согласует заявку?')
  await user.type(screen.getByLabelText('Ответ на вопрос Q-1'), 'Мой ответ')
  await user.click(screen.getByRole('button', { name: 'Отправить ответ' }))
  expect(await screen.findByText(/вне области проверки/)).toBeInTheDocument()
  // Форма и текст остаются: можно исправить и повторить.
  expect(screen.getByLabelText('Ответ на вопрос Q-1')).toBeInTheDocument()
})

it('410 объясняет истёкшую ссылку, отвеченные вопросы не показывают форму', async () => {
  stubApi({
    'GET /api/v1/shares/tok/questions': {
      body: [question({ id: 'q2', code: 'Q-2', status: 'answered', answer: answered })],
    },
  })
  mount()
  expect(await screen.findByText('Открытых вопросов в области проверки нет.')).toBeInTheDocument()
  expect(screen.queryByLabelText('Ответ на вопрос Q-2')).toBeNull()

  stubApi({
    'GET /api/v1/shares/tok/questions': { body: [question()] },
    'POST /api/v1/shares/tok/questions/q1/answer': {
      status: 410,
      body: { detail: 'Срок ссылки истёк' },
    },
  })
  const { user } = mount()
  await screen.findByText('Кто согласует заявку?')
  await user.type(screen.getByLabelText('Ответ на вопрос Q-1'), 'Ответ')
  await user.click(screen.getByRole('button', { name: 'Отправить ответ' }))
  expect(await screen.findByText(/Срок действия ссылки истёк/)).toBeInTheDocument()
})

it('403 объясняет, что по ссылке отвечать нельзя', async () => {
  stubApi({
    'GET /api/v1/shares/tok/questions': { body: [question()] },
    'POST /api/v1/shares/tok/questions/q1/answer': {
      status: 403,
      body: { detail: 'Отвечать на вопросы по ссылке может только проверяющий' },
    },
  })
  const { user } = mount()
  await screen.findByText('Кто согласует заявку?')
  await user.type(screen.getByLabelText('Ответ на вопрос Q-1'), 'Ответ')
  await user.click(screen.getByRole('button', { name: 'Отправить ответ' }))
  expect(await screen.findByText(/По этой ссылке отвечать на вопросы нельзя/)).toBeInTheDocument()
})
