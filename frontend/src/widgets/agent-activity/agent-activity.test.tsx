import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TooltipProvider } from '@/shared/ui'
import { stubApi } from '@/test/api-stub'
import { AgentActivityButton, agentActivityTitle } from './agent-activity'

function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const user = userEvent.setup()
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <AgentActivityButton projectId="p1" />
      </TooltipProvider>
    </QueryClientProvider>,
  )
  return { user }
}

const events = [
  {
    kind: 'source_added',
    at: '2026-10-04T10:00:00Z',
    title: 'Записка со встречи',
    token_name: 'Claude Code на ноутбуке',
    source_id: 's1',
  },
  {
    kind: 'answer_added',
    at: '2026-10-03T09:00:00Z',
    question_code: 'Q-2',
    detail: 'Согласование проводит главный инженер.',
    token_name: 'Проверка коллеги',
    share_link_id: 'link-1',
  },
]

afterEach(() => vi.unstubAllGlobals())

describe('журнал активности агента', () => {
  it('показывает материалы и ответы агента с именем токена и временем', async () => {
    stubApi({
      'GET /api/v1/projects/p1/agent-activity': { body: { items: events, total: 2 } },
    })
    const { user } = mount()
    await user.click(screen.getByRole('button', { name: 'Активность агента' }))
    const sheet = await screen.findByRole('dialog', { name: 'Активность агента' })
    expect(within(sheet).getByText('Источник добавлен агентом')).toBeVisible()
    expect(within(sheet).getByText('«Записка со встречи»')).toBeVisible()
    expect(within(sheet).getByText('Ответ дан агентом')).toBeVisible()
    expect(within(sheet).getByText('Вопрос Q-2')).toBeVisible()
    expect(within(sheet).getByText('Claude Code на ноутбуке')).toBeVisible()
    expect(within(sheet).getByText('Проверка коллеги')).toBeVisible()
    expect(within(sheet).getByText('По ссылке проверки')).toBeVisible()
    expect(within(sheet).getByText(/Согласование проводит/)).toBeVisible()
  })

  it('пустой журнал объясняет, что здесь появится', async () => {
    stubApi({
      'GET /api/v1/projects/p1/agent-activity': { body: { items: [], total: 0 } },
    })
    const { user } = mount()
    await user.click(screen.getByRole('button', { name: 'Активность агента' }))
    const sheet = await screen.findByRole('dialog', { name: 'Активность агента' })
    expect(await within(sheet).findByText('Агент пока ничего не делал')).toBeVisible()
    expect(within(sheet).getByText(/Здесь появятся материалы и ответы/)).toBeVisible()
  })

  it('ошибка загрузки — причина и повтор', async () => {
    stubApi({
      'GET /api/v1/projects/p1/agent-activity': {
        status: 500,
        body: { detail: 'Внутренняя ошибка' },
      },
    })
    const { user } = mount()
    await user.click(screen.getByRole('button', { name: 'Активность агента' }))
    const sheet = await screen.findByRole('dialog', { name: 'Активность агента' })
    expect(await within(sheet).findByText('Журнал не загрузился')).toBeVisible()
    expect(within(sheet).getByText('Внутренняя ошибка')).toBeVisible()
    expect(within(sheet).getByRole('button', { name: 'Повторить' })).toBeVisible()
  })

  it('заголовок события не выдумывает данные', () => {
    expect(agentActivityTitle({ kind: 'source_added', at: '2026-10-04T10:00:00Z' })).toBe(
      'Источник добавлен агентом',
    )
    expect(agentActivityTitle({ kind: 'answer_added', at: '2026-10-04T10:00:00Z' })).toBe(
      'Ответ дан агентом',
    )
    expect(agentActivityTitle({ kind: 'unknown', at: '2026-10-04T10:00:00Z' })).toBe(
      'Событие агента',
    )
  })
})
