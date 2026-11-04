import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from '@tanstack/react-router'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { choiceRequest, getModelChoice, useModelChoiceStore } from '@/entities/llm-credential'
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

const CAPS = {
  known: true,
  context_tokens: 1_000_000,
  max_output_tokens: 128_000,
  vision: true,
  pdf_input: true,
  tools: true,
  effort_levels: ['low', 'medium', 'high', 'xhigh', 'max'],
  effort_default: 'medium',
  accepts_temperature: false,
  prices: null,
}

const MODELS = [
  { id: 'claude-opus-5-5', label: 'x', capabilities: CAPS },
  {
    id: 'claude-haiku-5-5',
    label: 'y',
    capabilities: { ...CAPS, effort_levels: ['low', 'medium', 'high', 'max'] },
  },
  {
    id: 'plain-model',
    label: 'z',
    capabilities: { ...CAPS, effort_levels: [], effort_default: null },
  },
]

async function mount(items: ReturnType<typeof credential>[]) {
  stubApi({
    'GET /api/v1/auth/session': {
      body: { auth_enabled: true, user: { id: 'u1', email: 'a@b.ru' } },
    },
    'GET /api/v1/me/llm-credentials': { body: { items, storage_available: true } },
    'GET /api/v1/me/llm-credentials/c1/models': { body: { items: MODELS } },
    'GET /api/v1/me/llm-credentials/c2/models': { body: { items: MODELS } },
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
      await screen.findByRole('button', {
        name: 'Модель: Claude Opus 5.5 · обычно · ключ «Рабочий»',
      }),
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

  it('уровень работы сохраняется вместе с выбором модели и виден в метке', async () => {
    const { user } = await mount([credential('c1', 'Рабочий', true)])
    await user.click(await screen.findByRole('button', { name: /Модель:/ }))
    const group = await screen.findByRole('radiogroup', { name: 'Глубина работы' })
    expect(within(group).getByRole('radio', { name: 'Обычно' })).toBeChecked()
    // У Opus 5.5 есть «Очень тщательно»; уровни идут от быстрого к максимуму.
    expect(
      within(group)
        .getAllByRole('radio')
        .map((item) => item.getAttribute('value')),
    ).toEqual(['low', 'medium', 'high', 'xhigh', 'max'])
    await user.click(within(group).getByRole('radio', { name: 'Тщательно' }))
    expect(useModelChoiceStore.getState().choices.u1).toEqual({
      credentialId: 'c1',
      model: 'claude-opus-5-5',
      effort: 'high',
    })
    expect(choiceRequest(getModelChoice('u1'))).toEqual({
      credential_id: 'c1',
      model: 'claude-opus-5-5',
      profile: { effort: 'high' },
    })
    expect(
      await screen.findByRole('button', {
        name: 'Модель: Claude Opus 5.5 · тщательно · ключ «Рабочий»',
      }),
    ).toBeInTheDocument()
  })

  it('у модели без рассуждения уровень скрыт, а неподдерживаемый сбрасывается', async () => {
    const { user } = await mount([credential('c1', 'Рабочий', true)])
    useModelChoiceStore
      .getState()
      .set('u1', { credentialId: 'c1', model: 'claude-opus-5-5', effort: 'xhigh' })
    await user.click(await screen.findByRole('button', { name: /Модель:/ }))
    const model = await screen.findByRole('combobox', { name: 'Модель' })
    model.focus()
    await user.keyboard('{Enter}')
    await user.click(await screen.findByRole('option', { name: 'Claude Haiku 5.5' }))
    // У Haiku 5.5 нет «Очень тщательно»: уровень не переносится, берётся умолчание модели.
    expect(useModelChoiceStore.getState().choices.u1).toEqual({
      credentialId: 'c1',
      model: 'claude-haiku-5-5',
    })
    model.focus()
    await user.keyboard('{Enter}')
    await user.click(await screen.findByRole('option', { name: 'plain-model' }))
    await waitFor(() =>
      expect(screen.queryByRole('radiogroup', { name: 'Глубина работы' })).not.toBeInTheDocument(),
    )
  })
})
