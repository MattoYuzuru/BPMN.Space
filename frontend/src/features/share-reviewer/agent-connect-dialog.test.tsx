import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from '@tanstack/react-router'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { subscribeOnboardingSignals } from '@/shared/lib/onboarding-signals'
import { TooltipProvider } from '@/shared/ui'
import { stubApi } from '@/test/api-stub'
import { AgentConnectDialog } from './agent-connect-dialog'

const guest = { auth_enabled: true, user: null }
const signed = { auth_enabled: true, user: { id: 'u1', email: 'anna@company.ru' } }

// Сгенерированное значение для теста, не настоящий токен.
const SECRET = `bps_${'s'.repeat(43)}`
const COMMAND = `claude mcp add --transport http bpmn-space https://arch.example/mcp --header "Authorization: Bearer ${SECRET}"`

const issued = {
  token_id: 't1',
  secret: SECRET,
  name: 'Проверка коллеги',
  project_id: 'p1',
  lane_ids: ['Lane_1'],
  scopes: ['projects:read', 'questions:answer'],
  expires_at: '2026-12-04T00:00:00Z',
  mcp_url: 'https://arch.example/mcp',
  command: COMMAND,
}

function withProviders(ui: ReactNode, options: { router?: boolean } = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const user = userEvent.setup()
  const tree = (
    <QueryClientProvider client={client}>
      <TooltipProvider>{ui}</TooltipProvider>
    </QueryClientProvider>
  )
  if (!options.router) {
    render(tree)
    return { user, client }
  }
  const root = createRootRoute({ component: () => <>{ui}</> })
  const routes = [
    createRoute({ getParentRoute: () => root, path: '/login', component: () => <p>Вход</p> }),
  ]
  const router = createRouter({
    routeTree: root.addChildren(routes),
    history: createMemoryHistory({ initialEntries: ['/share/tok'] }),
  })
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <RouterProvider router={router} />
      </TooltipProvider>
    </QueryClientProvider>,
  )
  return { user, client }
}

const dialogProps = {
  token: 'tok',
  open: true,
  onOpenChange: () => {},
  shareRole: 'reviewer' as const,
  scopeText: 'Продажи',
}

afterEach(() => vi.unstubAllGlobals())

describe('AgentConnectDialog', () => {
  it('выпускает токен один раз: секрет, адрес MCP и готовая команда', async () => {
    const calls = stubApi({
      'GET /api/v1/auth/session': { body: signed },
      'POST /api/v1/shares/tok/agent-token': { status: 201, body: issued },
    })
    const signals: string[] = []
    const unsubscribe = subscribeOnboardingSignals((signal) => signals.push(signal.type))
    const { user } = withProviders(<AgentConnectDialog {...dialogProps} />)
    await user.click(await screen.findByRole('button', { name: 'Подключить агента' }))

    expect(await screen.findByLabelText('Токен агента')).toHaveValue(SECRET)
    expect(screen.getByLabelText('Настройка для Claude Code')).toHaveValue(COMMAND)
    const message = screen.getByLabelText('Сообщение для агента') as HTMLTextAreaElement
    expect(message.value).toContain('https://arch.example/agents.md')
    expect(screen.getByText('Продажи')).toBeInTheDocument()
    expect(screen.getByText(/Показывается один раз/)).toBeInTheDocument()
    expect(calls.find((call) => call.method === 'POST')?.path).toBe(
      '/api/v1/shares/tok/agent-token',
    )

    await user.click(screen.getByRole('button', { name: 'Копировать настройку' }))
    expect(await navigator.clipboard.readText()).toBe(COMMAND)
    expect(signals).toContain('agent.command.copied')
    unsubscribe()
  })

  it('гость видит предложение войти и не просит токен', async () => {
    const calls = stubApi({ 'GET /api/v1/auth/session': { body: guest } })
    withProviders(<AgentConnectDialog {...dialogProps} />, { router: true })
    const login = await screen.findByRole('link', { name: 'Войти, чтобы подключить' })
    expect(login).toHaveAttribute('href', `/login?redirect=${encodeURIComponent('/share/tok')}`)
    expect(screen.queryByRole('button', { name: 'Подключить агента' })).not.toBeInTheDocument()
    expect(calls.some((call) => call.method === 'POST')).toBe(false)
  })

  it('403 объясняет, что токен выдаётся только по ссылке проверки', async () => {
    stubApi({
      'GET /api/v1/auth/session': { body: signed },
      'POST /api/v1/shares/tok/agent-token': {
        status: 403,
        body: { detail: 'Токен агента выдаётся только по ссылке проверки' },
      },
    })
    const { user } = withProviders(<AgentConnectDialog {...dialogProps} />)
    await user.click(await screen.findByRole('button', { name: 'Подключить агента' }))
    expect(
      await screen.findByText('Токен агента выдаётся только по ссылке проверки.'),
    ).toBeVisible()
    expect(screen.queryByLabelText('Токен агента')).not.toBeInTheDocument()
  })

  it('сетевая ошибка — понятный текст и можно повторить', async () => {
    stubApi({
      'GET /api/v1/auth/session': { body: signed },
      'POST /api/v1/shares/tok/agent-token': {
        status: 500,
        body: { detail: 'Внутренняя ошибка' },
      },
    })
    const { user } = withProviders(<AgentConnectDialog {...dialogProps} />)
    await user.click(await screen.findByRole('button', { name: 'Подключить агента' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Внутренняя ошибка')
    expect(screen.getByRole('button', { name: 'Подключить агента' })).toBeEnabled()
  })

  it('у ссылки просмотра токена нет', async () => {
    stubApi({ 'GET /api/v1/auth/session': { body: signed } })
    withProviders(<AgentConnectDialog {...dialogProps} shareRole="viewer" />)
    expect(await screen.findByText('Токен агента выдаётся по ссылке проверки')).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Подключить агента' })).not.toBeInTheDocument()
  })
})

describe('секрет токена', () => {
  it('не остаётся в DOM и MutationCache после закрытия', async () => {
    stubApi({
      'GET /api/v1/auth/session': { body: signed },
      'POST /api/v1/shares/tok/agent-token': { status: 201, body: issued },
    })
    const { user, client } = withProviders(<AgentConnectDialog {...dialogProps} />)
    await user.click(await screen.findByRole('button', { name: 'Подключить агента' }))
    expect(await screen.findByLabelText('Токен агента')).toHaveValue(SECRET)
    await user.click(screen.getByRole('button', { name: 'Готово' }))

    expect(screen.queryByLabelText('Токен агента')).not.toBeInTheDocument()
    const values = [...document.querySelectorAll('input, textarea')].map(
      (element) => (element as HTMLInputElement).value,
    )
    expect(values.join(' ')).not.toContain(SECRET)
    expect(document.body.textContent).not.toContain(SECRET)
    const cached = client
      .getMutationCache()
      .getAll()
      .map((mutation) => JSON.stringify(mutation.state.data ?? null))
      .join(' ')
    expect(cached).not.toContain(SECRET)
  })
})
