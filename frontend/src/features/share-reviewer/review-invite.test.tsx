import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { SharedProject } from '@/entities/share'
import { TooltipProvider } from '@/shared/ui'
import { stubApi } from '@/test/api-stub'
import { ReviewInvite, reviewScopeText } from './review-invite'

const signed = { auth_enabled: true, user: { id: 'u1', email: 'anna@company.ru' } }

const shared = {
  role: 'reviewer',
  editor_requires_account: false,
  scope: { lane_ids: ['Lane_1', 'Lane_2'], lanes: ['Продажи', 'Склад'], whole_project: false },
  detail: { id: 'p1', title: 'Закупка' },
} as unknown as SharedProject

function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const user = userEvent.setup()
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <ReviewInvite token="tok" shared={shared} />
      </TooltipProvider>
    </QueryClientProvider>,
  )
  return { user }
}

afterEach(() => vi.unstubAllGlobals())

describe('ReviewInvite', () => {
  it('показывает область словами и оба действия', async () => {
    stubApi({
      'GET /api/v1/auth/session': { body: signed },
      'GET /api/v1/shares/tok/agent-prompt': {
        body: {
          text: 'Проверь',
          lane_ids: [],
          lanes: [],
          questions_recap: [],
          whole_project: false,
        },
      },
    })
    mount()
    expect(await screen.findByText('Продажи, Склад.')).toBeVisible()
    expect(screen.getByText('Проверка')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Запрос для агента' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Подключить агента' })).toBeVisible()
  })

  it('открывает запрос для агента и подключение', async () => {
    stubApi({
      'GET /api/v1/auth/session': { body: signed },
      'GET /api/v1/shares/tok/agent-prompt': {
        body: {
          text: 'Проверь дорожки',
          lane_ids: ['Lane_1'],
          lanes: ['Продажи'],
          questions_recap: [],
          whole_project: false,
        },
      },
    })
    const { user } = mount()
    await user.click(await screen.findByRole('button', { name: 'Запрос для агента' }))
    expect(await screen.findByRole('dialog', { name: 'Запрос для агента' })).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Готово' }))

    await user.click(screen.getByRole('button', { name: 'Подключить агента' }))
    const connect = await screen.findByRole('dialog', { name: 'Подключить агента' })
    expect(connect).toHaveTextContent('Продажи, Склад')
  })

  it('весь проект называется словами', () => {
    expect(reviewScopeText({ lane_ids: [], lanes: [], whole_project: true })).toBe('Весь проект')
    expect(reviewScopeText({ lane_ids: ['L1'], lanes: [], whole_project: false })).toBe(
      'Выбранные дорожки',
    )
  })
})

it('честно объясняет, что ответы оставит агент: формы ответа по ссылке нет', async () => {
  mount()
  expect(await screen.findByText(/Схема открыта только для чтения/)).toBeInTheDocument()
  expect(screen.getByText(/ответы на вопросы области оставит ваш агент/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Ответить/ })).not.toBeInTheDocument()
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
})
