import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { mcpCommand } from '@/entities/api-token'
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

  it('создаёт токен с правами по умолчанию и показывает секрет один раз', async () => {
    const calls = stubApi({
      'GET /api/v1/me/api-tokens': { body: { items: [] } },
      'GET /api/v1/projects': { body: page([{ id: 'p1', title: 'Договоры' }]) },
      'POST /api/v1/me/api-tokens': { status: 201, body: { ...token, secret: SECRET } },
    })
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
    expect(screen.getByText(/MCP-сервер появится позже/)).toBeInTheDocument()

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
