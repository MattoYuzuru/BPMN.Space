import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TooltipProvider } from '@/shared/ui'
import { stubApi } from '@/test/api-stub'
import { AgentPromptDialog } from './agent-prompt-dialog'

function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const user = userEvent.setup()
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <AgentPromptDialog token="tok" open onOpenChange={() => {}} />
      </TooltipProvider>
    </QueryClientProvider>,
  )
  return { user }
}

afterEach(() => vi.unstubAllGlobals())

describe('AgentPromptDialog', () => {
  it('показывает готовый текст только для чтения и копирует его', async () => {
    stubApi({
      'GET /api/v1/shares/tok/agent-prompt': {
        body: {
          text: 'Проверь дорожки «Продажи» и ответь на открытые вопросы.',
          lane_ids: ['Lane_1'],
          lanes: ['Продажи'],
          questions_recap: [
            { id: 'q1', code: 'Q-1', text: 'Кто?', status: 'open', severity: 'major' },
          ],
          whole_project: false,
        },
      },
    })
    const { user } = mount()
    const text = (await screen.findByLabelText('Текст запроса')) as HTMLTextAreaElement
    expect(text.value).toBe('Проверь дорожки «Продажи» и ответь на открытые вопросы.')
    expect(text).toHaveAttribute('readonly')
    expect(screen.getByText('Продажи')).toBeInTheDocument()
    expect(screen.getByText('Вопросов в области: 1')).toBeInTheDocument()
    expect(screen.getByText(/Секрета ссылки в тексте нет/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Копировать запрос' }))
    expect(await navigator.clipboard.readText()).toBe(text.value)
  })

  it('403 объясняет, что ссылка не даёт запрос, и предлагает повторить', async () => {
    stubApi({
      'GET /api/v1/shares/tok/agent-prompt': {
        status: 403,
        body: { detail: 'Ссылка проверки не позволяет' },
      },
    })
    mount()
    expect(await screen.findByText('Ссылка не даёт доступ к запросу для агента.')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Повторить' })).toBeVisible()
    expect(screen.queryByLabelText('Текст запроса')).not.toBeInTheDocument()
  })

  it('401 просит войти, 404 — ссылка недействительна', async () => {
    stubApi({
      'GET /api/v1/shares/tok/agent-prompt': { status: 401, body: { detail: 'Войдите' } },
    })
    mount()
    expect(
      await screen.findByText('Войдите в аккаунт: эта ссылка открывается после входа.'),
    ).toBeVisible()
    vi.unstubAllGlobals()
  })

  it('404 — ссылка недействительна или истекла', async () => {
    stubApi({
      'GET /api/v1/shares/tok/agent-prompt': { status: 404, body: { detail: 'Нет ссылки' } },
    })
    mount()
    expect(await screen.findByText('Ссылка недействительна или её срок истёк.')).toBeVisible()
  })

  it('сетевая ошибка — общее сообщение и повтор', async () => {
    stubApi({})
    mount()
    expect(await screen.findByText('Запрос не загрузился')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Повторить' })).toBeVisible()
  })
})
