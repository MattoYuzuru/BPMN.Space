import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from '@tanstack/react-router'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useModelChoiceStore } from '@/entities/llm-credential'
import { TooltipProvider } from '@/shared/ui'
import { stubApi } from '@/test/api-stub'
import { ModelPicker } from './model-picker'

const credential = (id: string, label: string, isDefault: boolean) => ({
  id,
  provider: 'anthropic',
  label,
  base_url: null,
  key_hint: 'wxyz',
  default_model: 'claude-opus-5-5',
  is_default: isDefault,
  created_at: '2026-11-01T00:00:00Z',
  last_used_at: null,
  last_error: null,
})

async function mount(items: ReturnType<typeof credential>[]) {
  stubApi({
    'GET /api/v1/auth/session': {
      body: { auth_enabled: true, user: { id: 'u1', email: 'a@b.ru' } },
    },
    'GET /api/v1/me/llm-credentials': { body: { items, storage_available: true } },
    'GET /api/v1/me/llm-credentials/c2/models': {
      body: {
        items: [
          { id: 'claude-opus-5-5', label: 'x' },
          { id: 'claude-haiku-5-5', label: 'y' },
        ],
      },
    },
  })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(['session'], { auth_enabled: true, user: { id: 'u1', email: 'a@b.ru' } })
  const root = createRootRoute({ component: ModelPicker })
  const router = createRouter({
    routeTree: root,
    history: createMemoryHistory({ initialEntries: ['/'] }),
  })
  const user = userEvent.setup()
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <RouterProvider router={router} />
      </TooltipProvider>
    </QueryClientProvider>,
  )
  return { user }
}

beforeEach(() => {
  window.localStorage.clear()
  useModelChoiceStore.setState({ choices: {} })
})
afterEach(() => vi.unstubAllGlobals())

describe('Выбор модели для запуска', () => {
  it('без ключей показывает сервер по умолчанию', async () => {
    await mount([])
    expect(
      await screen.findByRole('button', { name: /Модель: Сервер по умолчанию/ }),
    ).toBeInTheDocument()
  })

  it('с ключом по умолчанию показывает модель и название ключа', async () => {
    await mount([credential('c1', 'Рабочий', true)])
    expect(
      await screen.findByRole('button', { name: 'Модель: Claude Opus 5.5 · ключ «Рабочий»' }),
    ).toBeInTheDocument()
  })

  it('выбор другого ключа запоминается для пользователя', async () => {
    const { user } = await mount([
      credential('c1', 'Рабочий', true),
      credential('c2', 'Личный', false),
    ])
    await user.click(await screen.findByRole('button', { name: /Модель:/ }))
    const key = await screen.findByRole('combobox', { name: 'Ключ' })
    key.focus()
    await user.keyboard('{Enter}')
    await user.click(await screen.findByRole('option', { name: 'Личный' }))
    expect(useModelChoiceStore.getState().choices.u1).toEqual({
      credentialId: 'c2',
      model: 'claude-opus-5-5',
    })
    expect(window.localStorage.getItem('arkhitektor:model-choice:u1')).toContain('c2')
  })
})
