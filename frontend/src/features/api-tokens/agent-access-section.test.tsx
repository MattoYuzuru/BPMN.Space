import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { mcpCommand } from '@/entities/api-token'
import { useOnboardingUi } from '@/entities/onboarding'
import { useTourStore } from '@/features/onboarding/tour'
import { subscribeOnboardingSignals } from '@/shared/lib/onboarding-signals'
import { TooltipProvider } from '@/shared/ui'
import { stubApi } from '@/test/api-stub'
import { AgentAccessSection, projectsSummary } from './agent-access-section'

// Сгенерированное значение для теста, не настоящий токен.
const SECRET = `bps_${'t'.repeat(43)}`

const token = {
  id: 't1',
  name: 'Claude Code на ноутбуке',
  token_prefix: 'bps_tttttt',
  scopes: ['projects:read', 'questions:answer'],
  project_ids: null,
  expires_at: '2026-12-04T00:00:00Z',
  created_at: '2026-11-04T00:00:00Z',
  last_used_at: null,
  expired: false,
}

const page = (items: { id: string; title: string }[]) => ({
  items: items.map((item) => ({ ...item, access: 'owner' })),
  next_cursor: null,
  total: items.length,
})

function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const user = userEvent.setup()
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <AgentAccessSection />
      </TooltipProvider>
    </QueryClientProvider>,
  )
  return { user }
}

afterEach(() => vi.unstubAllGlobals())

describe('Доступ для агентов', () => {
  it('показывает токены с правами и проектами, но без секрета', async () => {
    stubApi({
      'GET /api/v1/me/api-tokens': {
        body: {
          items: [
            token,
            { ...token, id: 't2', name: 'Старый', expired: true, project_ids: ['p1'] },
          ],
        },
      },
      'GET /api/v1/projects': (call) => ({
        body: page(call.search.get('scope') === 'own' ? [{ id: 'p1', title: 'Договоры' }] : []),
      }),
    })
    mount()
    expect(await screen.findByText('Claude Code на ноутбуке')).toBeInTheDocument()
    expect(screen.getAllByText('Чтение проектов')).toHaveLength(2)
    expect(screen.getAllByText('Ответы на вопросы')).toHaveLength(2)
    expect(screen.getByText('Все проекты')).toBeInTheDocument()
    expect(screen.getAllByText('не использовался')).toHaveLength(2)
    expect(screen.getByText('Истёк')).toBeInTheDocument()
    expect(await screen.findByText('«Договоры»')).toBeInTheDocument()
    expect(document.body.textContent).not.toContain(SECRET)
  })

  it('пустой список', async () => {
    stubApi({
      'GET /api/v1/me/api-tokens': { body: { items: [] } },
      'GET /api/v1/projects': { body: page([]) },
    })
    mount()
    expect(await screen.findByText('Токенов нет')).toBeInTheDocument()
  })

  it('«Как подключить» просит клиентский тур, но не запускает его само', async () => {
    stubApi({
      'GET /api/v1/me/api-tokens': { body: { items: [] } },
      'GET /api/v1/projects': { body: page([]) },
    })
    const before = useOnboardingUi.getState().agentTourRequest
    const { user } = mount()
    await user.click(await screen.findByRole('button', { name: 'Как подключить' }))
    expect(useOnboardingUi.getState().agentTourRequest).toBe(before + 1)
    expect(useTourStore.getState().status).toBe('idle')
  })

  it('создаёт токен с правами по умолчанию и показывает секрет один раз', async () => {
    const calls = stubApi({
      'GET /api/v1/me/api-tokens': { body: { items: [] } },
      'GET /api/v1/projects': { body: page([{ id: 'p1', title: 'Договоры' }]) },
      'POST /api/v1/me/api-tokens': { status: 201, body: { ...token, secret: SECRET } },
    })
    // Тур волн 2–4 ждёт факты создания токена и копирования команды.
    const signals: string[] = []
    const unsubscribe = subscribeOnboardingSignals((signal) => signals.push(signal.type))
    const { user } = mount()
    await user.click(await screen.findByRole('button', { name: 'Создать токен' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByRole('checkbox', { name: /Чтение проектов/ })).toBeChecked()
    expect(within(dialog).getByRole('checkbox', { name: /Ответы на вопросы/ })).toBeChecked()
    expect(within(dialog).getByRole('checkbox', { name: /Удаление источников/ })).not.toBeChecked()
    const submit = within(dialog).getByRole('button', { name: 'Создать токен' })
    expect(submit).toBeDisabled()
    await user.type(within(dialog).getByLabelText('Название'), 'Claude Code на ноутбуке')
    await user.click(within(dialog).getByRole('checkbox', { name: /Добавление источников/ }))
    await user.click(submit)

    await waitFor(() => expect(calls.some((call) => call.method === 'POST')).toBe(true))
    const post = calls.find((call) => call.method === 'POST')
    expect(post?.body).toEqual({
      name: 'Claude Code на ноутбуке',
      scopes: ['projects:read', 'questions:answer', 'sources:write'],
      project_ids: null,
      expires_in_days: 30,
    })
    expect(await screen.findByText('Токен создан')).toBeInTheDocument()
    expect(screen.getByLabelText('Токен')).toHaveValue(SECRET)
    const command = screen.getByLabelText('Команда для Claude Code') as HTMLTextAreaElement
    expect(command.value).toBe(mcpCommand(window.location.origin, SECRET))
    expect(command.value).toContain('/mcp --header "Authorization: Bearer bps_')
    // MCP-сервер волны 2 работает: команда подключает его к Claude Code.
    expect(screen.getByText(/MCP-сервер работает/)).toBeInTheDocument()
    // Тур волн 2–4 ждёт факты создания токена и копирования команды.
    expect(signals).toContain('agent.token.created')
    await user.click(screen.getByRole('button', { name: 'Копировать команду' }))
    await waitFor(() => expect(signals).toContain('agent.command.copied'))
    unsubscribe()

    await user.click(screen.getByRole('button', { name: 'Готово' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(document.body.textContent).not.toContain(SECRET)
  })

  it('ограничивает токен выбранными проектами', async () => {
    const calls = stubApi({
      'GET /api/v1/me/api-tokens': { body: { items: [] } },
      'GET /api/v1/projects': (call) => ({
        body: page(
          call.search.get('scope') === 'own'
            ? [{ id: 'p1', title: 'Договоры' }]
            : [{ id: 'p2', title: 'Закупки' }],
        ),
      }),
      'POST /api/v1/me/api-tokens': {
        status: 201,
        body: { ...token, project_ids: ['p2'], secret: SECRET },
      },
    })
    const { user } = mount()
    await user.click(await screen.findByRole('button', { name: 'Создать токен' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('Название'), 'Коллега')
    await user.click(within(dialog).getByRole('radio', { name: 'Выбранные' }))
    const submit = within(dialog).getByRole('button', { name: 'Создать токен' })
    expect(submit).toBeDisabled()
    await user.click(await within(dialog).findByRole('checkbox', { name: 'Закупки' }))
    await user.click(submit)
    await waitFor(() => expect(calls.some((call) => call.method === 'POST')).toBe(true))
    expect(calls.find((call) => call.method === 'POST')?.body).toMatchObject({
      project_ids: ['p2'],
    })
  })

  it('не закрывается, пока токен создаётся, и показывает секрет после ответа', async () => {
    stubApi({
      'GET /api/v1/me/api-tokens': { body: { items: [] } },
      'GET /api/v1/projects': { body: page([]) },
      'POST /api/v1/me/api-tokens': { status: 201, body: { ...token, secret: SECRET } },
    })
    // Ответ на создание придерживаем, пока тест не попробует закрыть окно.
    const stubbed = globalThis.fetch
    let release: () => void = () => {}
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
      const method = input instanceof Request ? input.method : (init?.method ?? 'GET')
      if (
        method === 'POST' &&
        String(input instanceof Request ? input.url : input).includes('api-tokens')
      ) {
        await gate
      }
      return stubbed(input, init)
    })
    const { user } = mount()
    await user.click(await screen.findByRole('button', { name: 'Создать токен' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('Название'), 'Агент')
    await user.click(within(dialog).getByRole('button', { name: 'Создать токен' }))

    await waitFor(() =>
      expect(within(dialog).getByRole('button', { name: 'Отмена' })).toBeDisabled(),
    )
    await user.keyboard('{Escape}')
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(within(dialog).queryByRole('button', { name: 'Закрыть' })).toBeNull()

    release()
    expect(await screen.findByText('Токен создан')).toBeInTheDocument()
    expect(screen.getByLabelText('Токен')).toHaveValue(SECRET)
  })

  it('ошибку сервера показывает в форме', async () => {
    stubApi({
      'GET /api/v1/me/api-tokens': { body: { items: [] } },
      'GET /api/v1/projects': { body: page([]) },
      'POST /api/v1/me/api-tokens': {
        status: 409,
        body: { detail: 'Достигнут лимит действующих токенов (50): отзовите ненужные' },
      },
    })
    const { user } = mount()
    await user.click(await screen.findByRole('button', { name: 'Создать токен' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('Название'), 'Ещё один')
    await user.click(within(dialog).getByRole('button', { name: 'Создать токен' }))
    expect(await within(dialog).findByText(/лимит действующих токенов/)).toBeInTheDocument()
  })

  it('отзывает токен после подтверждения', async () => {
    const calls = stubApi({
      'GET /api/v1/me/api-tokens': { body: { items: [token] } },
      'GET /api/v1/projects': { body: page([]) },
      'DELETE /api/v1/me/api-tokens/t1': { status: 204 },
    })
    const { user } = mount()
    await user.click(
      await screen.findByRole('button', { name: 'Отозвать токен «Claude Code на ноутбуке»' }),
    )
    const confirm = await screen.findByRole('alertdialog')
    await user.click(within(confirm).getByRole('button', { name: 'Отозвать' }))
    await waitFor(() => expect(calls.some((call) => call.method === 'DELETE')).toBe(true))
  })
})

describe('projectsSummary', () => {
  const projects = [
    { id: 'a', title: 'Договоры' },
    { id: 'b', title: 'Закупки' },
    { id: 'c', title: 'Склад' },
  ]
  it('называет проекты или считает их', () => {
    expect(projectsSummary(null, projects)).toBe('Все проекты')
    expect(projectsSummary(['a', 'b'], projects)).toBe('«Договоры», «Закупки»')
    expect(projectsSummary(['a', 'b', 'c'], projects)).toBe('3\u00a0проекта')
    expect(projectsSummary(['x'], projects)).toBe('1\u00a0проект')
    expect(projectsSummary(['a'], undefined)).toBe('1\u00a0проект')
  })
})
